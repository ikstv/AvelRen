# Безпечний recovery handoff collector — дизайн

Мета: вивести конкретну доведено покинуту paired операцію з recovery_required і перейти зі старого прямого writer на сучасний spool collector. Лише локальна розробка/приймання; серверне виконання потребує окремого GO.

Окремий staged CLI тримає backup_lock та operator_lock на кожному кроці. Durable collector-handoff.json у тому самому state_dir блокує звичайні backup, recover і mutating control між кроками. CAS прив’язаний до exact generation, state/old/new manifest hashes, env/compose hashes, old/new image/source, container identity. Живий/reused owner або child PID, інший boot, foreign/active job чи drift означають відмову.

prepare: записати intent зі старим state; перевірити jobs незалежно children[]; прибрати лише власні stopped helpers; підтвердити stop старого collector; створити й перевірити safety SQL/Online SQLite/rollback spec; виконати offline legacy migration з read-only SQL.
switch: перевірити safety captures повторно; створити лише один зупинений candidate, зафіксувати identity; витримати повні 60 monotonic секунд; стартувати exact candidate. Повтор start_intent зупиняє лише доведений candidate й заново чекає 60 секунд.
finish: native off ACK, identity recheck й drain без last_error; durable state intent → resumed, потім complete. Цей результат не означає published backup.
rollback: підтверджений stop exact writer, pending=started=0 до й після очікування; відновити старий spec/image через durable reverse phases, 60 секунд між writers. Результат rolled_back/recovery_required, а не успішний backup.

Міграція не змінює SQL або payload/cycle state. Вона перевіряє кожен retained cycle проти read-only repeatable-read SQL, атомарно додає лише per-cycle provenance marker для точного audited legacy contract. Marker прив’язаний до seq, at, payload version/digest, writer identity та exact primary data. Replay/restore незалежно повторюють SQL-перевірку. Нові цикли без marker проходять modern strict. Старий restore allowlist не розширюється. Штатне prune aged ACK прибирає лише відповідний marker.

Crash між recreate та записом нового container ID навмисно fail closed: unknown container не приймається за власний. Це не автоматично відновлюване вікно; потрібна окрема перевірена операторська процедура. Інший boot також не дозволяє автоматичного takeover. Нічого не видаляти/переписувати для обходу guard.

Приймання: real Linux lease/fsync/proc contracts; fault injection та небезпечні відмови; legacy aged/unaged ACK, committed/uncommitted pending, started і SQL idempotence; real historical source fixture з synthetic HTTP, empty rollback, SIGKILL у persisted start_intent, повтор, native off ACK/drain; crypt publication/readback і штатний isolated paired restore. Синтетична image identity явно відокремлена від audited production identity.
