# Flexarr for Home Assistant

Every Apple TV, iPhone and iPad signed in to Flexarr becomes a media player in Home Assistant, and everything that plays (on those devices or in a browser) fires an event you can automate on: dim the lights when a film starts, bring them up when the credits roll.

## Install

Copy `custom_components/flexarr` into your Home Assistant `config/custom_components/` folder and restart Home Assistant. (It will move to its own repository for HACS once it's settled.)

Then **Settings › Devices & services › Add integration › Flexarr**, and enter:

- **Server address**: where Flexarr's web app is, for example `http://192.168.1.20:8383`.
- **API key**: from **Settings › Access** in Flexarr.

## What you get

**A media player for each device**, named as it is in Flexarr's sign-ins. It shows what's playing (title, show, season and episode, artwork, position) and has play, pause and stop. It's *idle* while Flexarr is open with nothing playing and *off* when Flexarr isn't open on it. A device signed in later appears by itself.

To start something, call `media_player.play_media` with a Flexarr title's id (the id in its address in the web app). A show's id plays the episode that device's profile is up to:

```yaml
action: media_player.play_media
target:
  entity_id: media_player.living_room_tv
data:
  media_content_id: 01a17ab1-0000-0000-0000-000000000000
  media_content_type: tvshow
```

**Triggers.** Each device has triggers for *started*, *paused*, *resumed*, *credits*, *ended* and *stopped* (pick the device in an automation's "Device" trigger). Credits fire where Flexarr has found the end credits (within ten seconds of them starting: players report every ten seconds); a title without them goes straight to *ended*.

Behind them is the `flexarr_playback` event, which also covers browsers. Its data:

| Field | |
|---|---|
| `type` | `started`, `paused`, `resumed`, `credits`, `ended` or `stopped` |
| `device_id` | the Home Assistant device (none for a browser) |
| `device_name` | the device or browser, as named in Flexarr |
| `profile` | whose profile is watching |
| `media_type` | `movie`, `episode`, `music` or `podcast` |
| `title`, `series_title`, `season`, `episode` | what's playing |
| `media_id` | its Flexarr id |
| `position`, `duration` | in seconds |

## Example: lights down for films

```yaml
automation:
  - alias: Lights down for a film
    triggers:
      - trigger: event
        event_type: flexarr_playback
        event_data:
          type: started
          media_type: movie
          device_name: Living room TV
    actions:
      - action: light.turn_on
        target: { entity_id: light.living_room }
        data: { brightness_pct: 10, transition: 5 }

  - alias: Lights up at the credits
    triggers:
      - trigger: event
        event_type: flexarr_playback
        event_data: { type: credits, device_name: Living room TV }
      - trigger: event
        event_type: flexarr_playback
        event_data: { type: stopped, device_name: Living room TV }
    actions:
      - action: light.turn_on
        target: { entity_id: light.living_room }
        data: { brightness_pct: 80, transition: 10 }
```

## How it works

The integration keeps `GET /api/v1/events` open (server-sent events: one `playback` event per change) and reconnects if it drops. It fetches `GET /api/v1/devices` every 30 seconds and straight after each event. Commands go to `POST /api/v1/devices/{id}/play`, `pause`, `resume` and `stop`. A playback that stops reporting counts as stopped after two minutes (fifteen if it was paused).

## Development

Tests run with [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component):

```sh
uv venv --python 3.13 && uv pip install pytest-homeassistant-custom-component
.venv/bin/python -m pytest
```
