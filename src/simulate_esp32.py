"""
M9 — Virtual ESP32 node, for testing the actuation loop without physical
hardware attached to this dev machine.

This is a software stand-in, not a claim that real firmware has been
flashed or tested — see `esp32_firmware/l2wo_node.ino` for the real
firmware (untested on hardware, since none is attached here) and
`docs/hardware-implementation-guide.md` for the honest boundary between
the two. This simulator exists so the MQTT contract (isolate command in,
confirmed actuator_state out, <5s round trip) can actually be exercised
and measured end-to-end, not just asserted in docs.

Subscribes to every segment's isolate topic, "closes the relay" after a
short simulated actuation delay, and publishes the confirmation.
"""

import argparse
import json
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

MQTT_HOST = "localhost"
MQTT_PORT = 1883
ACTUATION_DELAY_S = 0.4  # models real relay/servo travel time


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return
    segment_id = payload.get("segment_id")
    incident_id = payload.get("incident_id")
    print(f"[esp32-sim] isolate command received: segment={segment_id} incident={incident_id}")

    time.sleep(ACTUATION_DELAY_S)  # simulated relay/servo travel time

    confirmation = json.dumps({
        "incident_id": incident_id,
        "segment_id": segment_id,
        "state": "isolated",
        "at": datetime.now(timezone.utc).isoformat(),
    })
    client.publish(f"l2wo/{segment_id}/actuator_state", confirmation, qos=1)
    print(f"[esp32-sim] actuator confirmed isolated: segment={segment_id} incident={incident_id}")


def main():
    parser = argparse.ArgumentParser(description="Virtual ESP32 node for testing the actuation loop")
    parser.add_argument("--duration", type=float, default=None, help="seconds to run, default forever")
    args = parser.parse_args()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.subscribe("l2wo/+/isolate", qos=1)
    print("[esp32-sim] listening for isolate commands on l2wo/+/isolate")

    if args.duration:
        client.loop_start()
        time.sleep(args.duration)
        client.loop_stop()
    else:
        client.loop_forever()


if __name__ == "__main__":
    main()
