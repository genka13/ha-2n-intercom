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
API_SYSTEM_INFO = "/api/system/info"
API_SWITCH_CAPS = "/api/switch/caps"
API_SWITCH_STATUS = "/api/switch/status"
API_SWITCH_CTRL = "/api/switch/ctrl"

API_CAMERA_CAPS = "/api/camera/caps"
API_CAMERA_SNAPSHOT = "/api/camera/snapshot"

# Event logging (long-poll)
API_LOG_CAPS = "/api/log/caps"
API_LOG_SUBSCRIBE = "/api/log/subscribe"
API_LOG_PULL = "/api/log/pull"
API_LOG_UNSUBSCRIBE = "/api/log/unsubscribe"

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

