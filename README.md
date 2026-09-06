# PJLink Class 2 Simulator

This simulator implements PJLink Class 1 and Class 2 over TCP, plus Class 2 UDP discovery and optional status notifications.

The implementation follows the [JBMIA PJLink Specification Version 2.10](https://pjlink.jbmia.or.jp/english/data_cl2/PJLink_5-1.pdf). Authentication is intentionally disabled, so connections receive the standards-compliant `PJLINK 0\r` greeting.

## Run

```sh
python3 pjlink_simulator.py
```

The default TCP and UDP port is `4352`. A controller can confirm Class 2 support with `%1CLSS ?\r`, which returns `%1CLSS=2\r`.

Supported Class 2 commands are `INPT`, `INST`, `SNUM`, `SVER`, `INNM`, `IRES`, `RRES`, `FILT`, `RLMP`, `RFIL`, `SVOL`, `MVOL`, and `FREZ`. UDP discovery accepts `%2SRCH\r` and returns `%2ACKN=<MAC>\r`.

## Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `PJLINK_PORT` | `4352` | TCP and UDP listen port |
| `PJLINK_NAME` | `Projector_A` | Projector name and state filename prefix |
| `PJLINK_STATE_DIR` | `.` | Persistent state directory |
| `PJLINK_RESPONSE_DELAY` | `1` | Delay before each TCP command reply, in seconds; accepts non-negative finite numbers, including fractions and `0` for immediate replies |
| `PJLINK_MAC` | Generated from projector name | MAC returned by UDP discovery |
| `PJLINK_SEARCH_DELAY_MAX` | `10` | Maximum randomized discovery delay in seconds |
| `PJLINK_NOTIFY_HOST` | unset | Controller address for Class 2 UDP notifications |
| `PJLINK_NOTIFY_PORT` | `4352` | Controller notification port |

When notifications are configured, the simulator emits `LKUP` at startup and `POWR`/`INPT` after their state changes.

TCP command replies (including errors) wait one second by default to simulate a real device. The initial `PJLINK 0` greeting is immediate; UDP discovery uses its separate randomized delay. Commands on the same connection receive replies in order, each with its own delay. Set `PJLINK_RESPONSE_DELAY=0.5 python3 pjlink_simulator.py` for a half-second delay, or `PJLINK_RESPONSE_DELAY=0.5 docker compose up --build` when using Docker Compose. Python callers can override the environment with `PJLinkSimulator(response_delay=0.5)`; direct `process_command()` calls do not wait.

## Test

```sh
python3 -m unittest -v
```
