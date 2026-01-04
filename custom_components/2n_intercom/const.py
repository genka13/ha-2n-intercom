"""Constants for the 2N Intercom integration."""

DOMAIN = "2n_intercom"

# Platforms we expose
PLATFORMS = ["switch", "camera", "button", "binary_sensor", "sensor"]

# Config keys
CONF_USE_HTTPS = "use_https"
CONF_VERIFY_SSL = "verify_ssl"
CONF_AUTH_METHOD = "auth_method"

# Defaults
DEFAULT_USE_HTTPS = True
DEFAULT_VERIFY_SSL = True

AUTH_METHOD_DIGEST = "digest"
AUTH_METHOD_BASIC = "basic"

# 2N HTTP API endpoints

# Event logging (long-poll)

# Event defaults
DEFAULT_EVENT_PULL_TIMEOUT = 25  # seconds
DEFAULT_EVENT_CHANNEL_DURATION = 3600  # seconds

# Events we subscribe to by default (filtered by /api/log/caps)
DEFAULT_EVENT_FILTER = [
    "CallStateChanged",
    "MotionDetected",
    "DoorStateChanged",
    "SwitchStateChanged",
    "RexActivated",
    "NoiseDetected",
    "SilentAlarm",
    "CardEntered",
    "CodeEntered",
    "MobKeyEntered",
]

# RTSP stream profile (fixed endpoints on the device)
CONF_RTSP_STREAM = "rtsp_stream"
DEFAULT_RTSP_STREAM = "h264_stream"  # other options: h265_stream, mjpeg_stream

# Optional RTSP port override (default: 554)
CONF_RTSP_PORT = "rtsp_port"
DEFAULT_RTSP_PORT = 554

# Door release button uses this switch number (default: 1)
CONF_DOOR_RELEASE_SWITCH = "door_release_switch"
DEFAULT_DOOR_RELEASE_SWITCH = 1

# Pulse durations (seconds) for momentary event binary sensors
CONF_PULSE_REX = "pulse_rex_seconds"
DEFAULT_PULSE_REX = 5

CONF_PULSE_SILENT_ALARM = "pulse_silent_alarm_seconds"
DEFAULT_PULSE_SILENT_ALARM = 30

CONF_PULSE_INVALID_CREDENTIAL = "pulse_invalid_credential_seconds"
DEFAULT_PULSE_INVALID_CREDENTIAL = 10
