"""Support for MQTT cover devices."""
import logging

import voluptuous as vol
from asyncio import sleep

from homeassistant.components import cover, mqtt
from homeassistant.components.cover import (
    ATTR_POSITION,
    DEVICE_CLASSES_SCHEMA,
    SUPPORT_CLOSE,
    SUPPORT_OPEN,
    SUPPORT_SET_POSITION,
    CoverEntity,
)
from homeassistant.const import (
    CONF_DEVICE,
    CONF_DEVICE_CLASS,
    CONF_NAME,
    CONF_PAYLOAD_ON,
    CONF_PAYLOAD_OFF,
    STATE_CLOSED,
    STATE_CLOSING,
    STATE_OPEN,
    STATE_OPENING,
    STATE_UNKNOWN,
)
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.typing import ConfigType, HomeAssistantType

#from . import (
from homeassistant.components.mqtt.const import (
    ATTR_DISCOVERY_HASH
)
from homeassistant.const import CONF_UNIQUE_ID

from homeassistant.components.mqtt.mixins import (
    MqttAttributes,
    MqttAvailability,
    MqttDiscoveryUpdate,
    MqttEntityDeviceInfo,
    subscription,
)

from homeassistant.components.mqtt import (
#    ATTR_DISCOVERY_HASH,
    CONF_QOS,
    CONF_STATE_TOPIC,
#    CONF_UNIQUE_ID,
#    MqttAttributes,
#    MqttAvailability,
)
from homeassistant.components.mqtt.debug_info import log_messages
from homeassistant.components.mqtt.discovery import MQTT_DISCOVERY_NEW, clear_discovery_hash

_LOGGER = logging.getLogger(__name__)

CONF_VALUE_TEMPLATE_OPEN = "value_template_open"
CONF_VALUE_TEMPLATE_CLOSE = "value_template_close"
CONF_COMMAND_TOPIC_OPEN = "command_topic_open"
CONF_COMMAND_TOPIC_CLOSE = "command_topic_close"
CONF_CLOSE_TO_OPEN_TIME = "close_to_open_time"

DEFAULT_COVER_NAME = "MQTT Cover Relay"
DEFAULT_POSITION_CLOSED = 0
DEFAULT_POSITION_OPEN = 100
DEFAULT_RETAIN = False

OPEN_CLOSE_FEATURES = SUPPORT_OPEN | SUPPORT_CLOSE


def validate_options(value):
    """Validate options.

    If set position topic is set then get position topic is set as well.
    """
    if CONF_STATE_TOPIC not in value:
        raise vol.Invalid(
            "{} is mandatory".format(CONF_STATE_TOPIC)
        )

    if CONF_COMMAND_TOPIC_OPEN not in value:
        raise vol.Invalid(
            "{} is mandatory".format(COMMAND_TOPIC_OPEN)
        )

    if CONF_COMMAND_TOPIC_CLOSE not in value:
        raise vol.Invalid(
            "{} is mandatory".format(COMMAND_TOPIC_CLOSE)
        )

    if CONF_VALUE_TEMPLATE_OPEN not in value: 
        raise vol.Invalid(
            "{} is mandatory".format(CONF_VALUE_TEMPLATE_OPEN)
        )

    if CONF_VALUE_TEMPLATE_CLOSE not in value:
        raise vol.Invalid(
            "{} is mandatory".format(CONF_VALUE_TEMPLATE_CLOSE)
        )

    if CONF_PAYLOAD_ON not in value:
        raise vol.Invalid(
            "{} is mandatory".format(CONF_PAYLOAD_ON)
        )

    if CONF_PAYLOAD_OFF not in value:
        raise vol.Invalid(
            "{} is mandatory".format(CONF_PAYLOAD_OFF)
        )

    if CONF_CLOSE_TO_OPEN_TIME not in value:
        raise vol.Invalid(
            "{} is mandatory".format(CONF_CLOSE_TO_OPEN_TIME)
        ) 
        
    return value
    


PLATFORM_SCHEMA = vol.All(
    mqtt.MQTT_BASE_PLATFORM_SCHEMA.extend(
        {
            vol.Optional(CONF_UNIQUE_ID): cv.string,
            vol.Optional(CONF_DEVICE_CLASS): DEVICE_CLASSES_SCHEMA,
            vol.Optional(CONF_UNIQUE_ID): cv.string,
            vol.Optional(CONF_NAME, default=DEFAULT_COVER_NAME): cv.string,
            vol.Optional(CONF_STATE_TOPIC): mqtt.valid_subscribe_topic,
            vol.Optional(CONF_COMMAND_TOPIC_OPEN): mqtt.valid_publish_topic,
            vol.Optional(CONF_COMMAND_TOPIC_CLOSE): mqtt.valid_publish_topic,
            vol.Optional(CONF_VALUE_TEMPLATE_OPEN): cv.template,
            vol.Optional(CONF_VALUE_TEMPLATE_CLOSE): cv.template,
            vol.Optional(CONF_PAYLOAD_ON): cv.string,
            vol.Optional(CONF_PAYLOAD_OFF): cv.string,
            vol.Optional(CONF_CLOSE_TO_OPEN_TIME): cv.positive_int,
        }
    )
    .extend(mqtt.mixins.MQTT_AVAILABILITY_SCHEMA.schema),
    #.extend(mqtt.mixins.MQTT_JSON_ATTRS_SCHEMA.schema),
    validate_options,
)


async def async_setup_platform(
    hass: HomeAssistantType, config: ConfigType, async_add_entities, discovery_info=None
):
    """Set up MQTT cover through configuration.yaml."""
    await _async_setup_entity(config, async_add_entities)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up MQTT cover dynamically through MQTT discovery."""

    async def async_discover(discovery_payload):
        """Discover and add an MQTT cover."""
        discovery_data = discovery_payload.discovery_data
        try:
            config = PLATFORM_SCHEMA(discovery_payload)
            await _async_setup_entity(
                config, async_add_entities, config_entry, discovery_data
            )
        except Exception:
            clear_discovery_hash(hass, discovery_data[ATTR_DISCOVERY_HASH])
            raise

    async_dispatcher_connect(
        hass, MQTT_DISCOVERY_NEW.format(cover.DOMAIN, "mqtt"), async_discover
    )


async def _async_setup_entity(
    config, async_add_entities, config_entry=None, discovery_data=None
):
    """Set up the MQTT Cover."""
    async_add_entities([MqttCoverRelay(config, config_entry, discovery_data)])


class MqttCoverRelay(
    MqttAttributes,
    MqttAvailability,
    MqttDiscoveryUpdate,
    MqttEntityDeviceInfo,
    CoverEntity,
):
    """Representation of a cover that can be controlled using MQTT."""


    def __init__(self, config, config_entry, discovery_data):
        """Initialize the cover."""
        self._unique_id = config.get(CONF_UNIQUE_ID)
        self._position = None
        self._desiredPosition = None
        self._state = None
        self._sub_state = None

        # Load config
        self._setup_from_config(config)

        device_config = config.get(CONF_DEVICE)

        MqttAttributes.__init__(self, config)
        MqttAvailability.__init__(self, config)
        MqttDiscoveryUpdate.__init__(self, discovery_data, self.discovery_update)
        MqttEntityDeviceInfo.__init__(self, device_config, config_entry)


    async def async_added_to_hass(self):
        """Subscribe MQTT events."""
        await super().async_added_to_hass()
        await self._subscribe_topics()


    async def discovery_update(self, discovery_payload):
        """Handle updated discovery message."""
        config = PLATFORM_SCHEMA(discovery_payload)
        self._setup_from_config(config)
        await self.attributes_discovery_update(config)
        await self.availability_discovery_update(config)
        await self.device_info_discovery_update(config)
        await self._subscribe_topics()
        self.async_write_ha_state()


    def _setup_from_config(self, config):
        self._config = config


    async def _subscribe_topics(self):
        """(Re)Subscribe to topics."""
        template_open = self._config.get(CONF_VALUE_TEMPLATE_OPEN)
        if template_open is not None:
            template_open.hass = self.hass
        template_close = self._config.get(CONF_VALUE_TEMPLATE_CLOSE)
        if template_close is not None:
            template_close.hass = self.hass

        # For the moment no topics to subscribe
        topics = {}


        @callback
        @log_messages(self.hass, self.entity_id)
        def state_message_received(msg):
            """Handle new MQTT state messages."""
            """States will be controlled from here"""

            payload = msg.payload
            if template_open is not None:
                payload_open = template_open.async_render_with_possible_json_value(payload)
            if template_close is not None:
                payload_close = template_close.async_render_with_possible_json_value(payload)


            if payload_open == self._config[CONF_PAYLOAD_ON] and payload_close == self._config[CONF_PAYLOAD_ON]:
                _LOGGER.warning("Both ON and OFF are one, potential motor damage")   
            elif payload_open == self._config[CONF_PAYLOAD_ON]:
                _LOGGER.info("opening")   
                self._state = STATE_OPENING
            elif payload_close == self._config[CONF_PAYLOAD_ON]:
                _LOGGER.info("closing")   
                self._state = STATE_CLOSING
            elif payload_open == self._config[CONF_PAYLOAD_OFF] and payload_close == self._config[CONF_PAYLOAD_OFF]:
                if self.isMoving():
                    if self._position == 0:
                        self._state = STATE_CLOSED
                    else:
                        self._state = STATE_OPEN
                #if self._state == STATE_CLOSING:
                #    _LOGGER.info("closed")   
                #    self._state = STATE_CLOSED
                #elif self._state == STATE_OPENING:
                #    _LOGGER.info("open")   
                #    self._state = STATE_OPEN

            self.async_write_ha_state()


        if self._config.get(CONF_STATE_TOPIC):
            topics[CONF_STATE_TOPIC] = {
                "topic": self._config.get(CONF_STATE_TOPIC),
                "msg_callback": state_message_received,
                "qos": 0,
            }

        self._sub_state = await subscription.async_subscribe_topics(
            self.hass, self._sub_state, topics
        )


    async def async_will_remove_from_hass(self):
        """Unsubscribe when removed."""
        self._sub_state = await subscription.async_unsubscribe_topics(
            self.hass, self._sub_state
        )
        await MqttAttributes.async_will_remove_from_hass(self)
        await MqttAvailability.async_will_remove_from_hass(self)
        await MqttDiscoveryUpdate.async_will_remove_from_hass(self)


    @property
    def should_poll(self):
        """No polling needed."""
        return False


    @property
    def assumed_state(self):
        """Return true if we do optimistic updates."""
        return True


    @property
    def name(self):
        """Return the name of the cover."""
        return self._config[CONF_NAME]


    @property
    def is_closed(self):
        """Return true if the cover is closed or None if the status is unknown."""
        if self._state is None:
            return None

        return self._state == STATE_CLOSED


    @property
    def is_opening(self):
        """Return true if the cover is actively opening."""
        return self._state == STATE_OPENING


    @property
    def is_closing(self):
        """Return true if the cover is actively closing."""
        return self._state == STATE_CLOSING


    @property
    def current_cover_position(self):
        """Return current position of cover.

        None is unknown, 0 is closed, 100 is fully open.
        """
        return self._position


    @property
    def device_class(self):
        """Return the class of this sensor."""
        return self._config.get(CONF_DEVICE_CLASS)


    @property
    def supported_features(self):
        """Flag supported features."""
        supported_features = 0
        return OPEN_CLOSE_FEATURES | SUPPORT_SET_POSITION


    async def async_open_cover(self, **kwargs):
        self.hass.async_create_task(self.__async_open_cover())


    async def async_close_cover(self, **kwargs):
        self.hass.async_create_task(self.__async_close_cover())


    #
    # MYOWN Methods
    #

    async def __async_open_cover(self):
        _LOGGER.info("ACTION -> open")
        if self.isMoving():
            _LOGGER.info("ACTION -> is moving...")
            self._desiredPosition = 100
            return
        await self.async_relay_open_then_close(
            self._config.get(CONF_COMMAND_TOPIC_OPEN),
            self._config.get(CONF_CLOSE_TO_OPEN_TIME)
        )
        self._position = 100
        await self._check_desired_position()
    

    async def __async_close_cover(self, **kwargs):
        _LOGGER.info("ACTION -> close")
        if self.isMoving():
            _LOGGER.info("ACTION -> is moving...")
            self._desiredPosition = 0
            return
        await self.async_relay_open_then_close(
            self._config.get(CONF_COMMAND_TOPIC_CLOSE),
            self._config.get(CONF_CLOSE_TO_OPEN_TIME)
        )
        self._position = 0
        await self._check_desired_position()


    async def __async_set_position(self, position):
        # Round position
        position = position - (position % 5)
        if self._position == position:
            self.async_write_ha_state()
            return
        if self.isMoving():
            self._desiredPosition = position
            return
        if position == 0:
            await self.__async_close_cover()
            return
        if position == 100:
            await self.__async_open_cover()
            return

        if self._position == None:
            await self.__async_open_cover()

        positionDelta = self._position - position
        timeToMove = (abs(positionDelta) * self._config.get(CONF_CLOSE_TO_OPEN_TIME)) / 100

        if positionDelta < 0:
            # Must open
            topic = self._config.get(CONF_COMMAND_TOPIC_OPEN)
        else:
            # Must close
            topic = self._config.get(CONF_COMMAND_TOPIC_CLOSE)

        await self.async_relay_open_then_close(
            topic,
            timeToMove
        )

        self._position = position
        self.async_write_ha_state()

        await self._check_desired_position()


    def isMoving(self):
        if self._state == STATE_OPENING or self._state == STATE_CLOSING:
            return True
        return False


    async def async_relay_open_then_close(self, topic, time):
        mqtt.async_publish(
            self.hass,
            topic,
            self._config[CONF_PAYLOAD_ON],
            0,
            DEFAULT_RETAIN,
        )
        
        await sleep(time)

        mqtt.async_publish(
            self.hass,
            topic,
            self._config[CONF_PAYLOAD_OFF],
            0,
            DEFAULT_RETAIN,
        ) 

    
    async def _check_desired_position(self):
        # Called just after action, wait a little to status to be enabled
        counter = 0
        while self.isMoving():
            await sleep(0.5) 
            counter = counter + 1
            if counter > 10:
                break
        # 
        if self._desiredPosition is None:
            return
        if self._position == self._desiredPosition:
            self._desiredPosition = None
        else:
            if self._desiredPosition == 100:
                _LOGGER.info("DESIRED -> MUST OPEN")
                self.hass.async_create_task(self.__async_open_cover())
            elif self._desiredPosition == 0:
                _LOGGER.info("DESIRED -> MUST CLOSE")
                self.hass.async_create_task(self.__async_close_cover())
            else:
                _LOGGER.info("DESIRED -> SET")
                self.hass.async_create_task(self.async_set_cover_position(position=self._desiredPosition))
            self._desiredPosition = None    


    async def async_stop_cover(self, **kwargs):
        """Stop
        Never should be called, or in that case, should do nothing
        At the end of the day, we will call UP, DOWN, or set position
        so the position will be fixed

        This method is a coroutine.
        """


    async def async_set_cover_position(self, **kwargs):
        """Move the cover to a specific position """
        position = kwargs[ATTR_POSITION]
           
        self.hass.async_create_task(
            self.__async_set_position(position)
        )
        
        #percentage_position = position
        #if set_position_template is not None:
        #    position = set_position_template.async_render(**kwargs)
        #else:
        #    position = self.find_in_range_from_percent(position, COVER_PAYLOAD)

        #mqtt.async_publish(
        #    self.hass,
        #    self._config.get(CONF_SET_POSITION_TOPIC),
        #    position,
        #    self._config[CONF_QOS],
        #    self._config[CONF_RETAIN],
        #)
        #if self._optimistic:
        #    self._state = (
        #        STATE_CLOSED
        #        if percentage_position == self._config[CONF_POSITION_CLOSED]
        #        else STATE_OPEN
        #    )
        #    self._position = percentage_position
        #    self.async_write_ha_state()


    #def find_percentage_in_range(self, position, range_type=TILT_PAYLOAD):
        #"""Find the 0-100% value within the specified range."""
        # the range of motion as defined by the min max values
        # if range_type == COVER_PAYLOAD:
        #     max_range = self._config[CONF_POSITION_OPEN]
        #     min_range = self._config[CONF_POSITION_CLOSED]
        # else:
        #     max_range = self._config[CONF_TILT_MAX]
        #     min_range = self._config[CONF_TILT_MIN]
        # current_range = max_range - min_range
        # # offset to be zero based
        # offset_position = position - min_range
        # position_percentage = round(float(offset_position) / current_range * 100.0)

        # max_percent = 100
        # min_percent = 0
        # position_percentage = min(max(position_percentage, min_percent), max_percent)
        # if range_type == TILT_PAYLOAD and self._config[CONF_TILT_INVERT_STATE]:
        #     return 100 - position_percentage
        # return position_percentage
        #return 50

    # def find_in_range_from_percent(self, percentage, range_type=TILT_PAYLOAD):
    #     """
    #     Find the adjusted value for 0-100% within the specified range.

    #     if the range is 80-180 and the percentage is 90
    #     this method would determine the value to send on the topic
    #     by offsetting the max and min, getting the percentage value and
    #     returning the offset
    #     """
    #     if range_type == COVER_PAYLOAD:
    #         max_range = self._config[CONF_POSITION_OPEN]
    #         min_range = self._config[CONF_POSITION_CLOSED]
    #     else:
    #         max_range = self._config[CONF_TILT_MAX]
    #         min_range = self._config[CONF_TILT_MIN]
    #     offset = min_range
    #     current_range = max_range - min_range
    #     position = round(current_range * (percentage / 100.0))
    #     position += offset

    #     if range_type == TILT_PAYLOAD and self._config[CONF_TILT_INVERT_STATE]:
    #         position = max_range - position + offset
    #     return position

    @property
    def unique_id(self):
        """Return a unique ID."""
        return self._unique_id
