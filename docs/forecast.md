# Queue forecasting (future feature)

A note for the future, not a plan for tomorrow. Written on 7 August 2026, when data
collection had only just begun.

## The idea

Forecast the load of a **specific checkpoint** from accumulated history:
not "3 days of waiting right now", but "usually on Tuesday morning the wait here is
half of what it is on Friday evening".

This is something eCherha fundamentally lacks: it shows only the current snapshot and
does not store the past. Our advantage is not a better interface, but the fact that we
have history and the original source does not.

## Why per-checkpoint separately

Queues behave incompatibly. Yahodyn – Dorohusk holds a week of waiting at
1400+ vehicles, while Porubne – Siret stands empty for weeks. A single model over all
38 queues would learn the hospital average and fit no checkpoint.

Each checkpoint has its own regime: opening hours, the neighboring country's holidays,
throughput capacity, seasonality of freight traffic. The model is per-checkpoint.

## What is already being collected for this

`observations` is being populated **every minute since 6 August 2026**:

| field | usefulness for forecasting |
|---|---|
| `wait_time_seconds` | target variable |
| `vehicles_in_queue` | second target, often precedes a change in the wait |
| `is_paused` | explains dips that otherwise look like an anomaly |
| `time` | hour of day, day of week, holidays |
| `checkpoint_id` | model cross-section |

`collector_runs` records the gaps. This is not an incidental detail: a model trained on
a series with holes would treat our collector's downtime as a drop in the queue. Gaps
must be explicitly excluded from training, not silently interpolated.

`observations_hourly` (a continuous aggregate) already provides hourly averages —
most of the features will be built on them.

## When this can be started

**Not before 8–12 weeks have accumulated.** Weekly seasonality is the main
signal in this task, and to estimate it you need at least 8 repetitions of each
day of the week. On two weeks of data any model will learn the noise and produce
confident nonsense.

Roughly: **October–November 2026**.

## The order that makes sense

1. **A simple baseline first.** "Forecast = the same value it had on this
   day of the week at this hour a week ago." This is the seasonal naive forecast, and on
   such series it is surprisingly strong.
2. **Measure its error** (MAE in hours of waiting) separately per checkpoint.
3. **Any more complex model must beat the baseline** on the same data.
   If it does not beat it, we do not ship it, however fashionable it is.

Skipping step 1 is not allowed: without it, it is impossible to say whether anything
improved at all.

## What to account for in the features

- hour of day, day of week — the foundation;
- holidays of Ukraine **and the neighboring country**: a Polish day off stops the queue just
  as a Ukrainian one does;
- `is_paused` in the past — a queue behaves differently after a pause;
- long weekends and the start of the month (customs cycles);
- weather — probably not: the effect is small, and an external data source is one more
  dependency and one more point of failure.

## Limitations that must be named honestly

**Queues depend on events that are not in the data.** A checkpoint closure, a strike of
carriers on the Polish side, a change in customs rules, an air-raid alert.
The model will not predict them — and must not pretend that it can.

**The forecast must show uncertainty.** "Roughly 2–4 days" is more honest than
"3 days 14 hours". The latter creates false precision, and people will plan trips on
that precision.

**Feature #2 is planned to be paid.** If the forecast ever begins to influence its
firing, the same requirements apply to it as apply now to
`eta_alerts`: store a snapshot of the input data at the moment of the decision, so that a
disputed case can be examined.

## What not to do

Do not substitute the forecast for the current data. Right now `entry_eta` is a fact from
the original source (the measurement moment + `wait_time`), and that is exactly why it can
be trusted. The forecast must be a **separate field with a separate name**, so that the user
always understands where the measurement is and where the guess is.
