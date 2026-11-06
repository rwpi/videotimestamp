#import <AppKit/AppKit.h>
#import <pwd.h>
#import <unistd.h>

static NSString *VTSLoginHomeDirectory(void) {
    struct passwd *account = getpwuid(getuid());
    return account && account->pw_dir ? [NSString stringWithUTF8String:account->pw_dir] : @"/Users";
}

static NSURL *VTSOriginalFileURL(id value) {
    if ([value isKindOfClass:[NSURL class]]) {
        NSURL *url = (NSURL *)value;
        return url.isFileURL ? url : nil;
    }
    NSString *text = nil;
    if ([value isKindOfClass:[NSData class]]) {
        text = [[NSString alloc] initWithData:value encoding:NSUTF8StringEncoding];
    } else if ([value isKindOfClass:[NSString class]]) {
        text = value;
    }
    if (!text) {
        return nil;
    }
    NSURL *url = [NSURL URLWithString:text];
    return url.isFileURL ? url : nil;
}

static void VTSLoadOriginalFileURL(NSItemProvider *provider, void (^completion)(NSURL *)) {
    if ([provider hasItemConformingToTypeIdentifier:@"public.file-url"]) {
        [provider loadItemForTypeIdentifier:@"public.file-url"
                                   options:nil
                         completionHandler:^(id value, NSError *error) {
            completion(error ? nil : VTSOriginalFileURL(value));
        }];
        return;
    }

    // Finder supplies semantic movie/folder types without public.file-url.
    // Its open-in-place advertisements can be empty even when this request
    // succeeds, so the callback's isInPlace result is the deciding evidence.
    NSString *type = nil;
    for (NSString *candidate in @[@"public.movie", @"public.folder"]) {
        if ([provider hasItemConformingToTypeIdentifier:candidate]) {
            type = candidate;
            break;
        }
    }
    if (!type) {
        completion(nil);
        return;
    }
    [provider loadInPlaceFileRepresentationForTypeIdentifier:type
                                         completionHandler:^(NSURL *url, BOOL isInPlace, NSError *error) {
        // Only hand the original path to the app. The extension does not
        // access file contents, and must never retain a temporary copy.
        completion(!error && isInPlace ? VTSOriginalFileURL(url) : nil);
    }];
}

static BOOL VTSIsInsideCameraCard(NSString *path) {
    NSArray<NSString *> *components = [path.stringByResolvingSymlinksInPath pathComponents];
    if (components.count < 3 || ![components[1] isEqualToString:@"Volumes"]) {
        return NO;
    }
    NSString *volumePath = [@"/Volumes" stringByAppendingPathComponent:components[2]];
    NSURL *volumeURL = [NSURL fileURLWithPath:volumePath isDirectory:YES];
    NSNumber *isDirectory = nil;
    NSNumber *isRemovable = nil;
    NSNumber *isEjectable = nil;
    [volumeURL getResourceValue:&isDirectory forKey:NSURLIsDirectoryKey error:NULL];
    [volumeURL getResourceValue:&isRemovable forKey:NSURLVolumeIsRemovableKey error:NULL];
    [volumeURL getResourceValue:&isEjectable forKey:NSURLVolumeIsEjectableKey error:NULL];
    if (!isDirectory.boolValue || (!isRemovable.boolValue && !isEjectable.boolValue)) {
        return NO;
    }
    for (NSString *mediaRoot in @[@"DCIM", @"PRIVATE", @"private"]) {
        BOOL rootIsDirectory = NO;
        NSString *rootPath = [volumePath stringByAppendingPathComponent:mediaRoot];
        if ([[NSFileManager defaultManager] fileExistsAtPath:rootPath
                                                 isDirectory:&rootIsDirectory] && rootIsDirectory) {
            return YES;
        }
    }
    return NO;
}

@interface VTSQuickAction : NSObject <NSExtensionRequestHandling>
@end

@implementation VTSQuickAction

- (NSError *)errorWithDescription:(NSString *)description {
    return [NSError errorWithDomain:@"net.rwebber.vts.quick-action"
                               code:1
                           userInfo:@{NSLocalizedDescriptionKey: description}];
}

- (void)failRequest:(NSExtensionContext *)context description:(NSString *)description {
    NSLog(@"VTS Quick Action: %@", description);
    [context cancelRequestWithError:[self errorWithDescription:description]];
}

- (void)beginRequestWithExtensionContext:(NSExtensionContext *)context {
    NSString *action = [NSBundle mainBundle].infoDictionary[@"VTSFinderAction"];
    NSSet<NSString *> *supportedActions = [NSSet setWithArray:@[
        @"timestamp", @"remove-audio", @"merge", @"transcode",
        @"video-minutes", @"clip-order",
    ]];
    if (![supportedActions containsObject:action]) {
        [self failRequest:context description:@"The VTS Quick Action is not configured for a job."];
        return;
    }

    NSMutableArray<NSItemProvider *> *providers = [NSMutableArray array];
    for (id input in context.inputItems) {
        if (![input isKindOfClass:[NSExtensionItem class]]) {
            continue;
        }
        for (id attachment in ((NSExtensionItem *)input).attachments) {
            if ([attachment isKindOfClass:[NSItemProvider class]]) {
                [providers addObject:attachment];
            }
        }
    }
    if (providers.count == 0) {
        [self failRequest:context description:@"Finder did not send any selected files to VTS."];
        return;
    }

    // Resolve each original selected URL without retaining a temporary file
    // representation that could disappear after this extension returns.
    NSMutableArray *orderedURLs = [NSMutableArray arrayWithCapacity:providers.count];
    for (NSUInteger index = 0; index < providers.count; index++) {
        [orderedURLs addObject:NSNull.null];
    }
    dispatch_group_t loads = dispatch_group_create();
    [providers enumerateObjectsUsingBlock:^(NSItemProvider *provider, NSUInteger index, BOOL *stop) {
        (void)stop;
        dispatch_group_enter(loads);
        VTSLoadOriginalFileURL(provider, ^(NSURL *url) {
            if (url) {
                @synchronized (orderedURLs) {
                    orderedURLs[index] = url;
                }
            }
            dispatch_group_leave(loads);
        });
    }];

    dispatch_group_notify(loads, dispatch_get_main_queue(), ^{
        NSMutableArray<NSString *> *paths = [NSMutableArray arrayWithCapacity:orderedURLs.count];
        for (id value in orderedURLs) {
            if (![value isKindOfClass:[NSURL class]]) {
                [self failRequest:context description:@"Finder did not provide an original file URL for every selected item."];
                return;
            }
            NSURL *url = (NSURL *)value;
            NSString *path = (url.filePathURL ?: url).path;
            if (path.length == 0) {
                [self failRequest:context description:@"Finder provided a selected item without a local file path."];
                return;
            }
            [paths addObject:path];
        }
        if (![action isEqualToString:@"video-minutes"]) {
            for (NSString *path in paths) {
                if (VTSIsInsideCameraCard(path)) {
                    [self failRequest:context description:
                        @"This VTS action cannot write to a camera card. Import its footage first."];
                    return;
                }
            }
        }
        [self stageAndOpenAction:action paths:paths context:context];
    });
}

- (void)stageAndOpenAction:(NSString *)action
                    paths:(NSArray<NSString *> *)paths
                  context:(NSExtensionContext *)context {
    NSString *jobID = NSUUID.UUID.UUIDString.lowercaseString;
    NSDictionary *manifest = @{
        @"version": @3,
        @"job_id": jobID,
        @"action": action,
        @"paths": paths,
        @"auto_start": @YES,
    };
    NSString *jobDirectory = [VTSLoginHomeDirectory()
        stringByAppendingPathComponent:@"Library/Application Support/VTS/Finder Jobs"];
    NSError *error = nil;
    if (![[NSFileManager defaultManager] createDirectoryAtPath:jobDirectory
                                   withIntermediateDirectories:YES
                                                    attributes:nil
                                                         error:&error]) {
        [self failRequest:context description:[NSString stringWithFormat:
            @"VTS could not prepare the Quick Action job folder: %@", error.localizedDescription]];
        return;
    }
    NSData *data = [NSJSONSerialization dataWithJSONObject:manifest options:0 error:&error];
    NSString *manifestPath = [jobDirectory stringByAppendingPathComponent:
        [jobID stringByAppendingPathExtension:@"json"]];
    if (!data || ![data writeToFile:manifestPath options:NSDataWritingAtomic error:&error]) {
        [self failRequest:context description:[NSString stringWithFormat:
            @"VTS could not stage the Quick Action job: %@", error.localizedDescription]];
        return;
    }

    NSURL *jobURL = [NSURL URLWithString:[NSString stringWithFormat:@"vts://finder-job/%@", jobID]];
    NSURL *extensionURL = [NSBundle mainBundle].bundleURL;
    NSURL *applicationURL = extensionURL.URLByDeletingLastPathComponent
        .URLByDeletingLastPathComponent.URLByDeletingLastPathComponent;
    NSWorkspaceOpenConfiguration *configuration = [NSWorkspaceOpenConfiguration configuration];
    configuration.activates = NO;
    [[NSWorkspace sharedWorkspace] openURLs:@[jobURL]
                      withApplicationAtURL:applicationURL
                             configuration:configuration
                         completionHandler:^(NSRunningApplication *application, NSError *launchError) {
        (void)application;
        if (launchError) {
            [self failRequest:context description:[NSString stringWithFormat:
                @"VTS could not receive the Quick Action job: %@", launchError.localizedDescription]];
        } else {
            // This action starts a job; it does not replace Finder's inputs.
            [context completeRequestReturningItems:context.inputItems completionHandler:nil];
        }
    }];
}

@end
