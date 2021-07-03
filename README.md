# coverrelay
Xiaomi Aqara Relay as a roller shutter based on time

### Configuration

Must put this in configuration.yaml:

```
cover:
  ...
  - platform: coverrelay
    device_class: "shutter"
    unique_id: "shutter_salonMirador1"
    name: "Salon Persiana Mirador 1"
    state_topic: "zigbee2mqtt/0x00158d00044c7089"
    availability_topic: "zigbee2mqtt/bridge/state"
    command_topic_open: "zigbee2mqtt/<friendly_name>/l1/set"
    command_topic_close: "zigbee2mqtt/<friendly_name>/l2/set"
    value_template_open: "{{ value_json.state_l1 }}"
    value_template_close: "{{ value_json.state_l2 }}"
    payload_off: "OFF"
    payload_on: "ON"
    close_to_open_time: 22

`''
