import platform

def filter_hwaccel_methods():
    system = platform.system()
    cpu_info = platform.processor()

    if system == 'Darwin':
        return 'h264_videotoolbox'
    elif system == 'Windows':
        if 'Intel' in cpu_info:
            return 'h264_qsv'
        elif 'AMD' in cpu_info:
            return 'h264_amf'
        elif 'ARM' in cpu_info:
            return 'libx264'
    else:
        return 'libx264'
