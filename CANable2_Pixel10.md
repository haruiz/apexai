# CANable 2.0 to Google Pixel 10 Integration

Developer integration specification for streaming AiM MXL2 CAN output from **Edge #38**, a **BMW E46 Sedan with S54 motor swap**, to a **Google Pixel 10** through a **Jhoinrch RH-02 PRO / CANable 2.0** interface using SLCAN over USB-C OTG.

## Overview

This project connects the AiM MXL2 SmartyCam CAN output to an Android device for real-time vehicle telemetry ingestion, decoding, and downstream AI driving coach logic.

| Item | Value |
|---|---|
| Vehicle | BMW E46 Sedan - S54 Motor Swap |
| Programme Car | Edge #38 |
| Dash Logger | AiM MXL2 |
| Configuration Software | RaceStudio3 |
| ECU | AEM Standalone ECU |
| ECU CAN Input | AEM CAN protocol, 1 Mbit/s, receive only |
| Output CAN Bus | SmartyCam CAN, 1 Mbit/s |
| CAN Frame Type | 11-bit standard frames |
| Byte Order | Little Endian |
| CAN-to-USB Device | Jhoinrch RH-02 PRO / CANable 2.0 with SLCAN firmware |
| Android Device | Google Pixel 10 via USB-C OTG |
| GPS | AiM GPS09 external puck, 25 Hz source |
| IMU | MXL2 internal 3-axis accelerometer and gyroscope |
| Output Frames | 10 frames: `0x450` to `0x459` |
| Total Channels | 36 channels |

## System Architecture

The AiM MXL2 dash logger aggregates data from two primary input sources and re-transmits selected channels on the SmartyCam CAN output port.

### Input Sources

| Source | Description |
|---|---|
| `CANBUS1` | AEM standalone ECU using AEM CAN protocol at 1 Mbit/s. Provides RPM, gear, vehicle speed, engine coolant temperature, wheel speeds, oil temperature, DBW accelerator pedal position, brake switch, MIL output, and fuel pressure. |
| Internal MXL2 channels | AiM GPS09 position and speed, internal accelerometer and gyroscope, and analog sensors including oil pressure, analog oil temperature, brake pressure, and fuel level. |

### Output Port

| Port | Description |
|---|---|
| SmartyCam Port | Transmits aggregated data at 1 Mbit/s on 11-bit standard CAN frames. Connected to the RH-02 PRO / CANable 2.0 for SLCAN delivery to the Pixel 10. |

## Important Configuration Notes

- No TPMS system is fitted to Edge #38.
- No 29-bit extended frames are present on this bus.
- All frames are 11-bit standard frames.
- No Standard SmartyCam Stream frames `0x420` to `0x424` are configured.
- Edge #38 uses only the Extended Stream: `0x450` to `0x459`.
- The steering wheel angle sensor is not fitted.
- No `STEER ANGLE` channel is available on any path.

## Physical Connection

### Wiring

Connect the RLCAB015L cable from the MXL2 SmartyCam port to the RH-02 PRO screw terminal.

| RLCAB015L Wire | RH-02 PRO Terminal | Notes |
|---|---|---|
| Blue | CAN H | CAN high |
| White | CAN L | CAN low |
| GND | Leave unconnected | RH-02 PRO is galvanically isolated |
| 5V | Leave unconnected | 5V terminal is an output and is not required |

### Termination

The MXL2 has its internal 120 Ohm termination resistor enabled on the SmartyCam CAN port. Enable the termination switch on the RH-02 PRO as well.

This creates the correct two-node bus topology with one termination resistor at each end.

### Android USB-C OTG

Connect the RH-02 PRO USB-C output to the Pixel 10 USB-C port using a USB-C to USB-C cable with OTG support.

The Pixel 10 must grant USB host mode permissions for the CDC serial device on first connection.

## SLCAN Protocol

### Transport

The RH-02 PRO exposes the CAN bus as a USB CDC virtual serial device. On Android, it appears as a USB serial device compatible with [`usb-serial-for-android`](https://github.com/mik3y/usb-serial-for-android).

- Serial baud rate: `115200`
- CAN bus speed: `1 Mbit/s`
- Frame transport: terminated ASCII strings

### Frame Format

Each incoming SLCAN frame uses the following format:

```text
t<ID><DLC><DATA>\r
```

Example for CAN ID `0x450`:

```text
t4508A1B2C3D4E5F6A7B8\r
```

| Field | Example | Description |
|---|---|---|
| Frame type | `t` | Lowercase `t` means standard 11-bit frame |
| CAN ID | `450` | 3 hex digits, no `0x` prefix |
| DLC | `8` | Data length in bytes; always 8 in this protocol |
| Data | `A1B2C3D4E5F6A7B8` | 16 hex characters, 8-byte payload |
| Terminator | `\r` | Carriage return, `0x0D` |

### Encoding Principle

RaceStudio3 applies an encode multiplier before placing values into CAN frames. The Android decoder applies the reciprocal multiplier to recover the physical value.

| RaceStudio3 Encode Multiplier | Android Decode Formula |
|---|---|
| `x1` | `raw * 1` |
| `x10` | `raw * 0.1` |
| `x100` | `raw * 0.01` |
| `deg7` | `raw * 0.0000001` |

## CAN Frame Summary

Edge #38 uses the Extended Stream only.

| CAN ID | Frequency | DLC | Contents |
|---|---:|---:|---|
| `0x450` | 10 Hz | 8 | ECU RPM, ECU GEAR, ECU VEH SPD, ECU ECT |
| `0x451` | 50 Hz | 8 | ECU W SPD FL, ECU W SP FR, ECU W SPD RL, ECU W SPD RR |
| `0x452` | 10 Hz | 8 | ECU OIL T, no output, ECU DBW APP1, no output |
| `0x453` | 10 Hz | 8 | Fuel analog, no output, no output, ECU BRK SW |
| `0x454` | 10 Hz | 8 | ECU MIL OUT, no output x3 |
| `0x455` | 50 Hz | 8 | AccelerometerX, AccelerometerY, AccelerometerZ, no output |
| `0x456` | 50 Hz | 8 | GyroX, GyroY, GyroZ, no output |
| `0x457` | 20 Hz | 8 | Oil pressure analog, GPS Speed, ECU FUEL P, Brake Pressure analog |
| `0x458` | 1 Hz | 8 | Oil Temp analog, no output x3 |
| `0x459` | 20 Hz | 8 | GPS Latitude, GPS Longitude |

Notes:

- No frames `0x420` to `0x424` are configured.
- No frames `0x45A` to `0x45E` are configured.
- GPS Speed is carried in `0x457`, not in a dedicated `0x45E` frame.

## Extended Stream Frame Definitions

All frames use:

- 8-byte DLC
- Little Endian byte order
- 11-bit standard CAN frame format
- `[NO OUTPUT]` slots transmit zero and should not be decoded

### Frame `0x450` - ECU Block 1 - 10 Hz

| Bytes | Channel | Format | Decode | Unit |
|---|---|---|---|---|
| `0-1` | ECU RPM | U16 | `raw * 1` | rpm |
| `2-3` | ECU GEAR | U16 | `raw * 1` | gear |
| `4-5` | ECU VEH SPD | U16 | `raw * 0.1` | mph |
| `6-7` | ECU ECT | U16 | `raw * 0.1` | deg F |

`ECU GEAR` is valid on the AEM standalone ECU and can be used in coaching logic.

### Frame `0x451` - Wheel Speeds - 50 Hz

| Bytes | Channel | Format | Decode | Unit |
|---|---|---|---|---|
| `0-1` | ECU W SPD FL | U16 | `raw * 0.1` | mph |
| `2-3` | ECU W SP FR | U16 | `raw * 0.1` | mph |
| `4-5` | ECU W SPD RL | U16 | `raw * 0.1` | mph |
| `6-7` | ECU W SPD RR | U16 | `raw * 0.1` | mph |

Wheel speeds are output at 50 Hz by the AEM ECU. Verify on first capture.

### Frame `0x452` - ECU Block 2 - 10 Hz

| Bytes | Channel | Format | Decode | Unit |
|---|---|---|---|---|
| `0-1` | ECU OIL T | U16 | `raw * 0.1` | deg F |
| `2-3` | No output | - | - | - |
| `4-5` | ECU DBW APP1 | U16 | `raw * 0.01` | % |
| `6-7` | No output | - | - | - |

`ECU DBW APP1` is the drive-by-wire accelerator pedal position from 0 to 100%.

### Frame `0x453` - Fuel and Brake - 10 Hz

| Bytes | Channel | Format | Decode | Unit |
|---|---|---|---|---|
| `0-1` | Fuel analog | U16 | `raw * 0.01` | gal |
| `2-3` | No output | - | - | - |
| `4-5` | No output | - | - | - |
| `6-7` | ECU BRK SW | U16 | `raw * 1` | binary |

`ECU BRK SW`: `0 = released`, `1 = applied`.

### Frame `0x454` - MIL - 10 Hz

| Bytes | Channel | Format | Decode | Unit |
|---|---|---|---|---|
| `0-1` | ECU MIL OUT | U16 | `raw * 1` | # |
| `2-3` | No output | - | - | - |
| `4-5` | No output | - | - | - |
| `6-7` | No output | - | - | - |

### Frame `0x455` - Accelerometers - 50 Hz

| Bytes | Channel | Format | Decode | Unit |
|---|---|---|---|---|
| `0-1` | AccelerometerX / InlineAcc | S16 | `raw * 0.01` | g |
| `2-3` | AccelerometerY / LateralAcc | S16 | `raw * 0.01` | g |
| `4-5` | AccelerometerZ / VerticalAcc | S16 | `raw * 0.01` | g |
| `6-7` | No output | - | - | - |

Expected positive directions:

- InlineAcc: acceleration
- LateralAcc: right cornering
- VerticalAcc: upward bump

Verify sign convention on the first track session.

### Frame `0x456` - Gyroscopes - 50 Hz

| Bytes | Channel | Format | Decode | Unit |
|---|---|---|---|---|
| `0-1` | GyroX / RollRate | S16 | `raw * 0.1` | deg/s |
| `2-3` | GyroY / PitchRate | S16 | `raw * 0.1` | deg/s |
| `4-5` | GyroZ / YawRate | S16 | `raw * 0.1` | deg/s |
| `6-7` | No output | - | - | - |

Expected positive directions:

- RollRate: right roll
- PitchRate: nose up
- YawRate: clockwise from above

Verify sign convention on the first capture.

### Frame `0x457` - Pressures and GPS Speed - 20 Hz

| Bytes | Channel | Format | Decode | Unit |
|---|---|---|---|---|
| `0-1` | OilPressure analog | U16 | `raw * 0.1` | psi |
| `2-3` | GPS Speed | U16 | `raw * 0.1` | mph |
| `4-5` | ECU FUEL P | U16 | `raw * 0.1` | psi |
| `6-7` | Brake Pressure analog | U16 | `raw * 1` | psi |

GPS Speed is placed in `0x457`; there is no dedicated `0x45E` GPS speed frame for Edge #38.

### Frame `0x458` - Oil Temp Analog - 1 Hz

| Bytes | Channel | Format | Decode | Unit |
|---|---|---|---|---|
| `0-1` | Oil Temp analog | U16 | `raw * 0.1` | deg F |
| `2-3` | No output | - | - | - |
| `4-5` | No output | - | - | - |
| `6-7` | No output | - | - | - |

The analog oil temperature channel comes from the MXL2-AC physical sensor. The ECU oil temperature in `0x452` is the ECU sump sensor. Both are available, but ECU oil temperature updates faster and is preferred for coaching logic.

### Frame `0x459` - GPS Coordinates - 20 Hz

| Bytes | Channel | Format | Decode | Unit |
|---|---|---|---|---|
| `0-3` | GPS Latitude | S32 deg7 | `raw * 0.0000001` | decimal degrees |
| `4-7` | GPS Longitude | S32 deg7 | `raw * 0.0000001` | decimal degrees |

Frame `0x459` is configured at 20 Hz, below the GPS09 hardware source rate of 25 Hz.

## Complete Channel Decode Reference

| CAN ID | Bytes | Channel | Source | Frequency | Unit | Decode | Type |
|---|---|---|---|---:|---|---|---|
| `0x450` | `0-1` | ECU RPM | AEM ECU | 10 Hz | rpm | `raw * 1` | U16 |
| `0x450` | `2-3` | ECU GEAR | AEM ECU | 10 Hz | gear | `raw * 1` | U16 |
| `0x450` | `4-5` | ECU VEH SPD | AEM ECU | 10 Hz | mph | `raw * 0.1` | U16 |
| `0x450` | `6-7` | ECU ECT | AEM ECU | 10 Hz | deg F | `raw * 0.1` | U16 |
| `0x451` | `0-1` | ECU W SPD FL | AEM ECU | 50 Hz | mph | `raw * 0.1` | U16 |
| `0x451` | `2-3` | ECU W SP FR | AEM ECU | 50 Hz | mph | `raw * 0.1` | U16 |
| `0x451` | `4-5` | ECU W SPD RL | AEM ECU | 50 Hz | mph | `raw * 0.1` | U16 |
| `0x451` | `6-7` | ECU W SPD RR | AEM ECU | 50 Hz | mph | `raw * 0.1` | U16 |
| `0x452` | `0-1` | ECU OIL T | AEM ECU | 10 Hz | deg F | `raw * 0.1` | U16 |
| `0x452` | `4-5` | ECU DBW APP1 | AEM ECU | 10 Hz | % | `raw * 0.01` | U16 |
| `0x453` | `0-1` | Fuel | MXL2 Analog | 10 Hz | gal | `raw * 0.01` | U16 |
| `0x453` | `6-7` | ECU BRK SW | AEM ECU | 10 Hz | binary | `raw * 1` | U16 |
| `0x454` | `0-1` | ECU MIL OUT | AEM ECU | 10 Hz | # | `raw * 1` | U16 |
| `0x455` | `0-1` | InlineAcc / AccX | MXL2 Accel | 50 Hz | g | `raw * 0.01` | S16 |
| `0x455` | `2-3` | LateralAcc / AccY | MXL2 Accel | 50 Hz | g | `raw * 0.01` | S16 |
| `0x455` | `4-5` | VerticalAcc / AccZ | MXL2 Accel | 50 Hz | g | `raw * 0.01` | S16 |
| `0x456` | `0-1` | RollRate / GyroX | MXL2 Gyro | 50 Hz | deg/s | `raw * 0.1` | S16 |
| `0x456` | `2-3` | PitchRate / GyroY | MXL2 Gyro | 50 Hz | deg/s | `raw * 0.1` | S16 |
| `0x456` | `4-5` | YawRate / GyroZ | MXL2 Gyro | 50 Hz | deg/s | `raw * 0.1` | S16 |
| `0x457` | `0-1` | OilPressure | MXL2 Analog | 20 Hz | psi | `raw * 0.1` | U16 |
| `0x457` | `2-3` | GPS Speed | MXL2 GPS | 20 Hz | mph | `raw * 0.1` | U16 |
| `0x457` | `4-5` | ECU FUEL P | AEM ECU | 20 Hz | psi | `raw * 0.1` | U16 |
| `0x457` | `6-7` | Brake Pressure | MXL2 Analog | 20 Hz | psi | `raw * 1` | U16 |
| `0x458` | `0-1` | Oil Temp | MXL2 Analog | 1 Hz | deg F | `raw * 0.1` | U16 |
| `0x459` | `0-3` | GPS Latitude | MXL2 GPS | 20 Hz | deg | `raw * 0.0000001` | S32 |
| `0x459` | `4-7` | GPS Longitude | MXL2 GPS | 20 Hz | deg | `raw * 0.0000001` | S32 |

Type definitions:

- `U16`: unsigned int16, little endian
- `S16`: signed int16, little endian
- `S32`: signed int32, little endian

## Signed Channel Handling

The following channels are bidirectional and must be decoded as signed integers.

| Channel | Frame | Positive Direction | Type |
|---|---|---|---|
| InlineAcc / AccX | `0x455` | Acceleration; braking is negative | `int16_le` |
| LateralAcc / AccY | `0x455` | Right cornering; left is negative | `int16_le` |
| VerticalAcc / AccZ | `0x455` | Upward bump; downward is negative | `int16_le` |
| RollRate / GyroX | `0x456` | Right roll; left roll is negative | `int16_le` |
| PitchRate / GyroY | `0x456` | Nose up; nose down is negative | `int16_le` |
| YawRate / GyroZ | `0x456` | Clockwise from above; counterclockwise is negative | `int16_le` |
| GPS Latitude | `0x459` | North; south is negative | `int32_le` |
| GPS Longitude | `0x459` | East; west is negative | `int32_le` |

If a sign appears inverted on first capture, negate the decoded value in the decoder. Do not modify the frame definition.

## GPS Coordinate Decoding

GPS latitude and longitude are encoded in `deg7` format.

```java
double lat = rawLat * 0.0000001; // decimal degrees
double lon = rawLon * 0.0000001; // decimal degrees
```

Expected ranges for Northern California tracks:

| Channel | Expected Range | Example |
|---|---|---|
| Latitude | `+36.5` to `+38.5` | `+37.xxxxxxx` |
| Longitude | `-121` to `-123` | `-122.xxxxxxx` |

## Android Integration

### Recommended Library

Use `usb-serial-for-android` to communicate with the RH-02 PRO CDC serial device on the Pixel 10.

```gradle
implementation 'com.github.mik3y:usb-serial-for-android:3.4.6'
```

### Android Manifest

Add USB host support to `AndroidManifest.xml`:

```xml
<uses-feature android:name="android.hardware.usb.host" />
```

### Runtime USB Permission

Request USB permission before opening the port:

```java
PendingIntent permIntent = PendingIntent.getBroadcast(
    this,
    0,
    new Intent(ACTION_USB_PERMISSION),
    0
);

usbManager.requestPermission(device, permIntent);
```

### Java Decode Example

```java
// 1. Open the SLCAN serial port
UsbManager usbManager = (UsbManager) getSystemService(Context.USB_SERVICE);

UsbSerialDriver driver = UsbSerialProber.getDefaultProber()
    .probeDevice(usbManager.getDeviceList().values().iterator().next());

UsbSerialPort port = driver.getPorts().get(0);
port.open(usbManager.openDevice(driver.getDevice()));
port.setParameters(
    115200,
    8,
    UsbSerialPort.STOPBITS_1,
    UsbSerialPort.PARITY_NONE
);

// 2. Read and parse SLCAN frames
byte[] buffer = new byte[256];
int len = port.read(buffer, 1000);
String frame = new String(buffer, 0, len).trim();

if (frame.startsWith("t")) {
    int canId = Integer.parseInt(frame.substring(1, 4), 16);
    int dlc = Integer.parseInt(frame.substring(4, 5));
    byte[] data = hexToBytes(frame.substring(5, 5 + dlc * 2));

    switch (canId) {
        case 0x450: {
            int rpm = u16le(data, 0);
            int gear = u16le(data, 2);
            double speed = u16le(data, 4) * 0.1;
            double ect = u16le(data, 6) * 0.1;
            break;
        }
        case 0x452: {
            double oilTempEcu = u16le(data, 0) * 0.1;
            double pedalPos = u16le(data, 4) * 0.01;
            break;
        }
        case 0x455: {
            double inlineG = s16le(data, 0) * 0.01;
            double lateralG = s16le(data, 2) * 0.01;
            double verticalG = s16le(data, 4) * 0.01;
            break;
        }
        case 0x456: {
            double rollRate = s16le(data, 0) * 0.1;
            double pitchRate = s16le(data, 2) * 0.1;
            double yawRate = s16le(data, 4) * 0.1;
            break;
        }
        case 0x457: {
            double oilPressure = u16le(data, 0) * 0.1;
            double gpsSpeed = u16le(data, 2) * 0.1;
            double fuelPressure = u16le(data, 4) * 0.1;
            double brakePressure = u16le(data, 6) * 1.0;
            break;
        }
        case 0x459: {
            double lat = s32le(data, 0) * 0.0000001;
            double lon = s32le(data, 4) * 0.0000001;
            break;
        }
    }
}

private static int u16le(byte[] data, int offset) {
    return ((data[offset + 1] & 0xFF) << 8) | (data[offset] & 0xFF);
}

private static short s16le(byte[] data, int offset) {
    return (short)(((data[offset + 1] & 0xFF) << 8) | (data[offset] & 0xFF));
}

private static int s32le(byte[] data, int offset) {
    return ((data[offset + 3] & 0xFF) << 24)
        | ((data[offset + 2] & 0xFF) << 16)
        | ((data[offset + 1] & 0xFF) << 8)
        | (data[offset] & 0xFF);
}

private static byte[] hexToBytes(String hex) {
    int len = hex.length();
    byte[] data = new byte[len / 2];
    for (int i = 0; i < len; i += 2) {
        data[i / 2] = (byte)(
            (Character.digit(hex.charAt(i), 16) << 4)
            + Character.digit(hex.charAt(i + 1), 16)
        );
    }
    return data;
}
```

## CAN ID Collision Registry

The SmartyCam CAN port is an independent isolated bus. The following IDs are in use.

| CAN ID | Frame Type | Owner |
|---|---|---|
| `0x450` | 11-bit standard | AiM MXL2 Extended Stream |
| `0x451` | 11-bit standard | AiM MXL2 Extended Stream |
| `0x452` | 11-bit standard | AiM MXL2 Extended Stream |
| `0x453` | 11-bit standard | AiM MXL2 Extended Stream |
| `0x454` | 11-bit standard | AiM MXL2 Extended Stream |
| `0x455` | 11-bit standard | AiM MXL2 Extended Stream |
| `0x456` | 11-bit standard | AiM MXL2 Extended Stream |
| `0x457` | 11-bit standard | AiM MXL2 Extended Stream |
| `0x458` | 11-bit standard | AiM MXL2 Extended Stream |
| `0x459` | 11-bit standard | AiM MXL2 Extended Stream |

No 29-bit extended frames are present. No TPMS system is fitted. There is no known collision risk.

## Known Constraints and Outstanding Items

| Constraint | Detail |
|---|---|
| No Steering Angle | Steering wheel angle sensor is not fitted. No `STEER ANGLE` channel is available. Coaching logic must not depend on steering angle. |
| No TPMS | No tire pressure, tire temperature, or TPMS alarm channels are available. |
| No SmartyCam Standard Stream | `0x420` to `0x424` are not configured. The Android decoder must not expect these frame IDs. |
| GPS Speed in `0x457` | GPS Speed occupies bytes `2-3` of `0x457`; it is not available in a dedicated `0x45E` frame. |
| Wheel Speed 50 Hz | `0x451` wheel speeds are output at 50 Hz by the AEM ECU. Verify on first capture. |
| Signed Channel Verification | All six IMU channels are signed and require sign convention verification during the first track session. If inverted, negate in the decoder. |
| ECU OIL T vs Analog Oil Temp | ECU OIL T in `0x452` updates at 10 Hz and is preferred for coaching logic. Analog Oil Temp in `0x458` updates at 1 Hz. |
| ECU GEAR Valid | Unlike the MSS54HP DME on the #10 car, the AEM standalone ECU outputs valid gear position. This can be used in coaching logic. |

## Recommended First-Capture Validation Checklist

Use the first live CAN capture to confirm the following before enabling coaching logic:

- Confirm SLCAN frames arrive as `t<ID><DLC><DATA>\r`.
- Confirm only IDs `0x450` to `0x459` are present.
- Confirm no `0x420` to `0x424` frames are present.
- Confirm wheel speeds in `0x451` arrive near 50 Hz.
- Confirm GPS speed is decoded from bytes `2-3` of `0x457`.
- Confirm GPS coordinates from `0x459` fall within expected track-location ranges.
- Confirm all accelerometer and gyroscope signs match the expected direction convention.
- Confirm `ECU GEAR` is valid and stable enough for coaching logic.
- Confirm ECU oil temperature and analog oil temperature behavior, then select the appropriate one for the use case.

## License / Usage

This README was generated from the CANable 2.0 to Google Pixel 10 Developer Integration Specification v1.0 for Edge #38.
