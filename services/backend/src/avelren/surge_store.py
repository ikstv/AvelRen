"""Транзакційні епізоди: стан worker та скасування повідомлень."""

from datetime import UTC, datetime, timedelta

from psycopg.rows import dict_row

from .surge_events import Episode, SurgeState, advance_state, utc
from .surge_model import KYIV, SUPPORTED_CHECKPOINTS, Observation, detect_growth, predict_surge


async def expire_alerts(conn, event_id: int, now: datetime, *, invalid_only=False) -> None:
    # In one transaction: transition pending and enqueue durable cancel.
    condition = (
        """
        AND NOT EXISTS (
            SELECT 1 FROM surge_subscriptions s
            JOIN devices d ON d.id=s.device_id
            JOIN surge_events e ON e.id=a.event_id
            WHERE s.device_id=a.device_id AND s.checkpoint_id=e.checkpoint_id
              AND 'surge_v1'=ANY(d.notification_capabilities)
              AND ((e.kind='surge_forecast' AND s.forecast_enabled)
                OR (e.kind='surge_started' AND s.fact_enabled))
        )
    """
        if invalid_only
        else ""
    )
    await conn.execute(
        """
        WITH closing AS (
            UPDATE surge_alerts a SET status='expired'
            WHERE event_id=%s AND status='pending'
        """
        + condition
        + """
            RETURNING id,event_id,device_id
        )
        INSERT INTO notification_cancels(kind,alert_id,device_id,created_at)
        SELECT e.kind,c.id,c.device_id,%s
        FROM closing c JOIN surge_events e ON e.id=c.event_id
        ON CONFLICT(kind,alert_id) DO NOTHING
    """,
        (event_id, now),
    )
    if invalid_only:
        # ACK survives unsubscribe/re-enable. A cancelled expired alert gets a
        # new ID on re-enable; delayed old pushes/cancels cannot affect it.
        cursor = conn.cursor(row_factory=dict_row)
        await cursor.execute(
            "SELECT id,device_id FROM surge_alerts a "
            "WHERE event_id=%s AND status='expired' " + condition,
            (event_id,),
        )
        for row in await cursor.fetchall():
            await conn.execute(
                "SELECT discard_disabled_surge_alert(%s,%s)", (row["id"], row["device_id"])
            )


async def attach_alerts(conn, event_id: int, now: datetime) -> None:
    await expire_alerts(conn, event_id, now, invalid_only=True)
    await conn.execute(
        """
        INSERT INTO surge_alerts(event_id,device_id,next_attempt_at,created_at)
        SELECT e.id,s.device_id,%s,%s
        FROM surge_events e JOIN surge_subscriptions s ON s.checkpoint_id=e.checkpoint_id
        JOIN devices d ON d.id=s.device_id
        WHERE e.id=%s AND e.closed_at IS NULL AND e.expires_at>%s
          AND 'surge_v1'=ANY(d.notification_capabilities)
          AND ((e.kind='surge_forecast' AND s.forecast_enabled)
            OR (e.kind='surge_started' AND s.fact_enabled))
        ON CONFLICT(event_id,device_id) DO NOTHING
    """,
        (now, now, event_id, now),
    )


async def process_checkpoint(conn, checkpoint_id: int, now: datetime) -> None:
    now = utc(now)
    async with conn.transaction():
        cur = conn.cursor(row_factory=dict_row)
        await cur.execute("SELECT pg_advisory_xact_lock(163514,%s)", (checkpoint_id,))
        await cur.execute(
            "INSERT INTO surge_checkpoint_state(checkpoint_id) VALUES(%s) ON CONFLICT DO NOTHING",
            (checkpoint_id,),
        )
        await cur.execute(
            "SELECT * FROM surge_checkpoint_state WHERE checkpoint_id=%s FOR UPDATE",
            (checkpoint_id,),
        )
        stored = await cur.fetchone()
        await cur.execute(
            (
                "SELECT * FROM surge_events WHERE checkpoint_id=%s AND closed_at IS "
                "NULL ORDER BY id FOR UPDATE"
            ),
            (checkpoint_id,),
        )
        active = {r["kind"]: r for r in await cur.fetchall()}

        def episode(kind):
            row = active.get(kind)
            return Episode(row["started_at"], row["updated_at"], row["expires_at"]) if row else None

        state = SurgeState(
            episode("surge_forecast"),
            episode("surge_started"),
            stored["forecast_armed"],
            stored["last_observation_at"],
        )
        await cur.execute(
            """
            SELECT time,vehicles_in_queue,is_paused FROM observations
            WHERE checkpoint_id=%s AND time BETWEEN %s AND %s ORDER BY time
        """,
            (checkpoint_id, now - timedelta(hours=4, minutes=3), now),
        )
        observations = [
            Observation(r["time"], r["vehicles_in_queue"], r["is_paused"])
            for r in await cur.fetchall()
        ]
        observed = observations[-1].time if observations else now - timedelta(days=1)
        prediction = None
        prediction_id = None
        last_hour = stored["last_forecast_hour"]
        local_hour = now.astimezone(KYIV).replace(minute=0, second=0, microsecond=0).astimezone(UTC)
        retry_failed = False
        if checkpoint_id in SUPPORTED_CHECKPOINTS and last_hour == local_hour:
            await cur.execute(
                "SELECT issued_at,score FROM surge_predictions WHERE checkpoint_id=%s "
                "ORDER BY issued_at DESC LIMIT 1",
                (checkpoint_id,),
            )
            previous = await cur.fetchone()
            retry_failed = bool(
                previous and previous["score"] is None and previous["issued_at"] < observed
            )
        if (
            checkpoint_id in SUPPORTED_CHECKPOINTS
            and (last_hour != local_hour or retry_failed)
            and local_hour <= observed <= now
            and now - observed <= timedelta(minutes=3)
        ):
            prediction = predict_surge(checkpoint_id, observations, observed)
            await cur.execute(
                """
                INSERT INTO surge_predictions
                    (checkpoint_id,issued_at,window_start,window_end,model_version,score,reason)
                VALUES(%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(checkpoint_id,issued_at,model_version) DO NOTHING RETURNING id
            """,
                (
                    checkpoint_id,
                    prediction.issued_at,
                    prediction.window_start,
                    prediction.window_end,
                    prediction.model_version,
                    prediction.score,
                    prediction.reason,
                ),
            )
            row = await cur.fetchone()
            if row:
                prediction_id = row["id"]
            last_hour = local_hour
        growth = detect_growth(observations, now)
        decision = advance_state(state, prediction, growth, observed, now)
        # Close before INSERT, satisfying one-active partial index atomically.
        for kind, reason in decision.closed:
            row = active.pop(kind, None)
            if row:
                await cur.execute(
                    "UPDATE surge_events SET closed_at=%s,close_reason=%s WHERE id=%s",
                    (now, reason, row["id"]),
                )
                await expire_alerts(conn, row["id"], now)
        for kind, ep in [
            ("surge_forecast", decision.state.forecast),
            ("surge_started", decision.state.fact),
        ]:
            if ep is None:
                continue
            row = active.get(kind)
            if row is None:
                await cur.execute(
                    """
                    INSERT INTO surge_events
                        (checkpoint_id,kind,started_at,updated_at,expires_at,prediction_id,growth)
                    VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id
                """,
                    (
                        checkpoint_id,
                        kind,
                        ep.started_at,
                        ep.updated_at,
                        ep.expires_at,
                        prediction_id if kind == "surge_forecast" else None,
                        growth if kind == "surge_started" else None,
                    ),
                )
                event_id = (await cur.fetchone())["id"]
            else:
                event_id = row["id"]
                await cur.execute(
                    """
                    UPDATE surge_events SET updated_at=%s,expires_at=%s,
                        prediction_id=COALESCE(%s,prediction_id),growth=COALESCE(%s,growth)
                    WHERE id=%s
                """,
                    (
                        ep.updated_at,
                        ep.expires_at,
                        prediction_id if kind == "surge_forecast" else None,
                        growth if kind == "surge_started" and ep.updated_at == observed else None,
                        event_id,
                    ),
                )
            await attach_alerts(conn, event_id, now)
        await cur.execute(
            """
            UPDATE surge_checkpoint_state SET last_observation_at=%s,
                last_forecast_hour=%s,forecast_armed=%s,last_growth_at=%s
            WHERE checkpoint_id=%s
        """,
            (
                decision.state.last_observation_at,
                last_hour,
                decision.state.forecast_armed,
                decision.state.fact.updated_at if decision.state.fact else stored["last_growth_at"],
                checkpoint_id,
            ),
        )


async def disable_monitoring(conn, now: datetime) -> None:
    async with conn.transaction():
        cur = conn.cursor(row_factory=dict_row)
        await cur.execute(
            (
                "UPDATE surge_events SET closed_at=%s,close_reason='disabled' WHERE "
                "closed_at IS NULL RETURNING id"
            ),
            (now,),
        )
        for row in await cur.fetchall():
            await expire_alerts(conn, row["id"], now)
