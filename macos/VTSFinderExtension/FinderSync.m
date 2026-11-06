#import <AppKit/AppKit.h>
#import <FinderSync/FinderSync.h>
#import <pwd.h>
#import <unistd.h>

static NSString *VTSUserHomeDirectory(void) {
    struct passwd *account = getpwuid(getuid());
    if (account != NULL && account->pw_dir != NULL) {
        return [NSString stringWithUTF8String:account->pw_dir];
    }
    return @"/Users";
}

@interface VTSFinderSync : FIFinderSync
@end

@implementation VTSFinderSync

- (instancetype)init {
    self = [super init];
    if (self) {
        NSNotificationCenter *workspaceNotifications =
            [NSWorkspace sharedWorkspace].notificationCenter;
        [workspaceNotifications addObserver:self
                                   selector:@selector(mountedVolumesDidChange:)
                                       name:NSWorkspaceDidMountNotification
                                     object:nil];
        [workspaceNotifications addObserver:self
                                   selector:@selector(mountedVolumesDidChange:)
                                       name:NSWorkspaceDidUnmountNotification
                                     object:nil];
        [self refreshDirectoryURLs];
    }
    return self;
}

- (void)dealloc {
    [[NSWorkspace sharedWorkspace].notificationCenter removeObserver:self];
}

- (void)mountedVolumesDidChange:(NSNotification *)notification {
    (void)notification;
    [self refreshDirectoryURLs];
}

- (void)refreshDirectoryURLs {
    // NSHomeDirectory points at the extension's sandbox container. Finder
    // needs the actual login home so the menu covers local files.
    NSMutableSet<NSURL *> *directories = [NSMutableSet setWithObject:
        [NSURL fileURLWithPath:VTSUserHomeDirectory() isDirectory:YES]];

    // A mounted card is an item inside /Volumes, so right-clicking the card
    // itself only reaches this extension when the parent is registered too.
    [directories addObject:[NSURL fileURLWithPath:@"/Volumes" isDirectory:YES]];

    // Finder Sync does not reliably treat /Volumes as a recursive scope after
    // removable media disconnects and reconnects. Register every currently
    // mounted volume explicitly, and refresh the list on mount changes.
    NSArray<NSURL *> *mountedVolumes = [[NSFileManager defaultManager]
        mountedVolumeURLsIncludingResourceValuesForKeys:nil
        options:0];
    for (NSURL *volumeURL in mountedVolumes) {
        NSString *path = volumeURL.path;
        if ([path hasPrefix:@"/Volumes/"]) {
            [directories addObject:volumeURL];
        }
    }
    [FIFinderSyncController defaultController].directoryURLs = directories;
}

- (NSMenu *)menuForMenuKind:(FIMenuKind)menuKind {
    BOOL itemMenu = menuKind == FIMenuKindContextualMenuForItems;
    BOOL containerMenu = menuKind == FIMenuKindContextualMenuForContainer;
    // The sidebar is where a card is usually right-clicked, and it is the only
    // menu kind the card item below answers for.
    BOOL sidebarMenu = menuKind == FIMenuKindContextualMenuForSidebar;
    if (!itemMenu && !containerMenu && !sidebarMenu) {
        return nil;
    }
    NSURL *iconURL = [[NSBundle mainBundle] URLForResource:@"VTS" withExtension:@"icns"];
    NSImage *icon = iconURL ? [[NSImage alloc] initWithContentsOfURL:iconURL] : nil;
    if (icon) {
        icon.size = NSMakeSize(16.0, 16.0);
    }

    BOOL isCameraCard = [self cameraCardVolumeURL] != nil;
    if (sidebarMenu) {
        // The sidebar answers for a camera card and nothing else, so a
        // right-click on any other place in it keeps Finder's own menu.
        return isCameraCard ? [self cameraCardMenuWithIcon:icon] : nil;
    }
    if (isCameraCard) {
        // Jobs that create or rename files must never run on the evidence card.
        return [self cameraCardMenuWithIcon:icon];
    }
    for (NSURL *url in [self jobSelectionURLs]) {
        if ([self isInsideCameraCardURL:url]) {
            return [self cameraCardReadOnlyMenuWithIcon:icon];
        }
    }
    return [self standaloneMenuWithIcon:icon];
}

// The card's own item. It appears only on a camera card, so the menu never
// offers to import from the archive drive or from an ordinary folder.
- (NSMenuItem *)importTodayItemWithIcon:(NSImage *)icon {
    NSMenuItem *item = [[NSMenuItem alloc]
        initWithTitle:@"Import Today's Videos"
        action:@selector(startImportToday:)
        keyEquivalent:@""];
    item.target = self;
    item.image = icon;
    return item;
}

// A card carries the only copy of the footage until it is imported, so the
// menu offers importing and the one job that reads without writing. Every
// other VTS job would create or rename files on the card itself.
- (NSMenu *)cameraCardMenuWithIcon:(NSImage *)icon {
    NSMenu *menu = [[NSMenu alloc] initWithTitle:@""];
    [menu addItem:[self importTodayItemWithIcon:icon]];
    NSMenuItem *runtimeItem = [[NSMenuItem alloc]
        initWithTitle:@"Calculate Runtime"
        action:@selector(startVideoMinutes:)
        keyEquivalent:@""];
    runtimeItem.target = self;
    runtimeItem.image = icon;
    [menu addItem:runtimeItem];
    return menu;
}

// A clip or subfolder on the card is still evidence. Import Today belongs on
// the volume's own menu; descendants offer only the read-only runtime job.
- (NSMenu *)cameraCardReadOnlyMenuWithIcon:(NSImage *)icon {
    NSMenu *menu = [[NSMenu alloc] initWithTitle:@""];
    NSMenuItem *runtimeItem = [[NSMenuItem alloc]
        initWithTitle:@"Calculate Runtime"
        action:@selector(startVideoMinutes:)
        keyEquivalent:@""];
    runtimeItem.target = self;
    runtimeItem.image = icon;
    [menu addItem:runtimeItem];
    return menu;
}

- (BOOL)isInsideCameraCardURL:(NSURL *)url {
    if (!url.isFileURL) {
        return NO;
    }
    NSArray<NSString *> *components = [(url.filePathURL ?: url).URLByResolvingSymlinksInPath.path pathComponents];
    if (components.count < 3 || ![components[1] isEqualToString:@"Volumes"]) {
        return NO;
    }
    NSString *volumePath = [@"/Volumes" stringByAppendingPathComponent:components[2]];
    return [self isCameraCardVolumeURL:[NSURL fileURLWithPath:volumePath isDirectory:YES]];
}

// The one right-clicked item, when it is a camera card and nothing else. The
// archive drive, a mounted disk image, a folder inside a card and a
// multiple-item selection all return nil, so the import item stays off menus
// where it would copy nothing or copy from the wrong place.
- (NSURL *)cameraCardVolumeURL {
    NSArray<NSURL *> *selection = [self jobSelectionURLs];
    if (selection.count != 1) {
        return nil;
    }
    NSURL *candidate = selection.firstObject;
    return [self isCameraCardVolumeURL:candidate] ? candidate : nil;
}

// An SD card here means a removable volume at the top of /Volumes holding one
// of the media roots the importer actually scans: DCIM for Panasonic and
// LawMate cards, PRIVATE for AVCHD and XAVC ones.
- (BOOL)isCameraCardVolumeURL:(NSURL *)url {
    if (!url.isFileURL) {
        return NO;
    }
    NSURL *volumeURL = url.filePathURL ?: url;
    NSArray<NSString *> *components = volumeURL.pathComponents;
    if (components.count != 3 || ![components[1] isEqualToString:@"Volumes"]) {
        return NO;
    }

    BOOL accessed = [volumeURL startAccessingSecurityScopedResource];
    NSNumber *isDirectory = nil;
    NSNumber *isRemovable = nil;
    NSNumber *isEjectable = nil;
    [volumeURL getResourceValue:&isDirectory forKey:NSURLIsDirectoryKey error:NULL];
    [volumeURL getResourceValue:&isRemovable forKey:NSURLVolumeIsRemovableKey error:NULL];
    [volumeURL getResourceValue:&isEjectable forKey:NSURLVolumeIsEjectableKey error:NULL];
    // A card in the built-in reader reports as internal, so only removable or
    // ejectable can be required here.
    BOOL isCard = isDirectory.boolValue && (isRemovable.boolValue || isEjectable.boolValue);
    BOOL holdsCameraMedia = NO;
    if (isCard) {
        NSFileManager *files = [NSFileManager defaultManager];
        for (NSString *mediaRoot in @[@"DCIM", @"PRIVATE", @"private"]) {
            NSString *rootPath = [volumeURL.path stringByAppendingPathComponent:mediaRoot];
            BOOL rootIsDirectory = NO;
            if ([files fileExistsAtPath:rootPath isDirectory:&rootIsDirectory] && rootIsDirectory) {
                holdsCameraMedia = YES;
                break;
            }
        }
    }
    if (accessed) {
        [volumeURL stopAccessingSecurityScopedResource];
    }
    return isCard && holdsCameraMedia;
}

// These six file operations use the standalone app's saved settings and run
// immediately, so they sit directly in the Finder menu rather than behind a
// submenu that has to be opened to reach any of them. Interactive trimming
// stays in the app, where ranges can be set.
- (NSMenu *)standaloneMenuWithIcon:(NSImage *)icon {
    NSMenu *menu = [[NSMenu alloc] initWithTitle:@""];
    NSArray<NSDictionary<NSString *, NSString *> *> *items = @[
        @{@"title": @"Timestamp Videos", @"action": NSStringFromSelector(@selector(startTimestamp:))},
        @{@"title": @"Remove Audio", @"action": NSStringFromSelector(@selector(startRemoveAudio:))},
        @{@"title": @"Merge Clips", @"action": NSStringFromSelector(@selector(startMerge:))},
        @{@"title": @"Transcode Videos", @"action": NSStringFromSelector(@selector(startTranscode:))},
        @{@"title": @"Calculate Runtime", @"action": NSStringFromSelector(@selector(startVideoMinutes:))},
        @{@"title": @"Order Clips", @"action": NSStringFromSelector(@selector(startClipOrder:))},
    ];
    for (NSDictionary<NSString *, NSString *> *job in items) {
        NSMenuItem *item = [[NSMenuItem alloc]
            initWithTitle:job[@"title"]
            action:NSSelectorFromString(job[@"action"])
            keyEquivalent:@""];
        item.target = self;
        // Every item carries the VTS icon because none of them sit under a
        // parent item naming the app any more.
        item.image = icon;
        [menu addItem:item];
    }
    return menu;
}

// "Today" is the operator's local day, not the card's or UTC's, so the date
// the menu promises matches the date the importer filters on.
- (void)startImportToday:(id)sender {
    NSDateFormatter *formatter = [[NSDateFormatter alloc] init];
    formatter.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"];
    formatter.calendar = [NSCalendar calendarWithIdentifier:NSCalendarIdentifierGregorian];
    formatter.timeZone = [NSTimeZone localTimeZone];
    formatter.dateFormat = @"yyyy-MM-dd";
    [self startFinderJobWithAction:@"import-files"
                           options:@{@"import_date": [formatter stringFromDate:[NSDate date]]}];
}

- (void)startClipOrder:(id)sender { [self startJobWithAction:@"clip-order"]; }
- (void)startTimestamp:(id)sender { [self startJobWithAction:@"timestamp"]; }
- (void)startRemoveAudio:(id)sender { [self startJobWithAction:@"remove-audio"]; }
- (void)startMerge:(id)sender { [self startJobWithAction:@"merge"]; }
- (void)startTranscode:(id)sender { [self startJobWithAction:@"transcode"]; }
- (void)startVideoMinutes:(id)sender { [self startJobWithAction:@"video-minutes"]; }

- (NSArray<NSURL *> *)jobSelectionURLs {
    FIFinderSyncController *controller = [FIFinderSyncController defaultController];
    NSArray<NSURL *> *items = controller.selectedItemURLs;
    if (items.count > 0) {
        return items;
    }
    NSURL *target = controller.targetedURL;
    return target ? @[target] : @[];
}

- (NSURL *)containingApplicationURL {
    NSURL *extensionURL = [NSBundle mainBundle].bundleURL;
    return [[[
        extensionURL URLByDeletingLastPathComponent
    ] URLByDeletingLastPathComponent] URLByDeletingLastPathComponent];
}

- (NSString *)jobURLScheme {
    return @"vts";
}

- (void)startJobWithAction:(NSString *)action {
    [self startFinderJobWithAction:action options:nil];
}

- (void)startFinderJobWithAction:(NSString *)action
                         options:(NSDictionary<NSString *, id> *)options {
    NSMutableArray<NSString *> *paths = [NSMutableArray array];
    for (NSURL *url in [self jobSelectionURLs]) {
        if (!url.isFileURL) {
            continue;
        }
        BOOL accessed = [url startAccessingSecurityScopedResource];
        NSURL *pathURL = url.filePathURL ?: url;
        if (pathURL.path.length > 0) {
            [paths addObject:pathURL.path];
        }
        if (accessed) {
            [url stopAccessingSecurityScopedResource];
        }
    }
    if (paths.count == 0) {
        return;
    }

    NSString *jobID = NSUUID.UUID.UUIDString.lowercaseString;
    NSMutableDictionary *manifest = [@{
        @"version": @3,
        @"job_id": jobID,
        @"action": action,
        @"paths": paths,
        @"auto_start": @YES,
    } mutableCopy];
    if (options) {
        manifest[@"options"] = options;
    }
    NSString *jobDirectory = [VTSUserHomeDirectory()
        stringByAppendingPathComponent:@"Library/Application Support/VTS/Finder Jobs"];
    NSError *error = nil;
    [[NSFileManager defaultManager]
        createDirectoryAtPath:jobDirectory
        withIntermediateDirectories:YES
        attributes:nil
        error:&error];
    if (error) {
        NSLog(@"VTS could not create its Finder job folder: %@", error);
        return;
    }
    NSData *manifestData = [NSJSONSerialization dataWithJSONObject:manifest options:0 error:&error];
    NSString *manifestPath = [jobDirectory stringByAppendingPathComponent:
        [jobID stringByAppendingPathExtension:@"json"]];
    if (!manifestData || ![manifestData writeToFile:manifestPath options:NSDataWritingAtomic error:&error]) {
        NSLog(@"VTS could not write Finder job %@: %@", jobID, error);
        return;
    }

    NSString *urlText = [NSString stringWithFormat:@"%@://finder-job/%@", [self jobURLScheme], jobID];
    NSURL *jobURL = [NSURL URLWithString:urlText];
    if (!jobURL) {
        NSLog(@"VTS could not form Finder job URL %@", urlText);
        return;
    }
    // Deliver to this extension's containing app, not another VTS build that
    // LaunchServices may have cached for the same URL scheme.
    NSWorkspaceOpenConfiguration *configuration = [NSWorkspaceOpenConfiguration configuration];
    configuration.activates = NO;
    [[NSWorkspace sharedWorkspace]
        openURLs:@[jobURL]
        withApplicationAtURL:[self containingApplicationURL]
        configuration:configuration
        completionHandler:^(NSRunningApplication *application, NSError *launchError) {
            if (launchError) {
                NSLog(@"VTS could not open Finder job %@: %@", jobID, launchError);
            }
        }];
}

@end
