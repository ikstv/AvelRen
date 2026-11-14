# Production deployment record — 2026-11-14

This record captures the production state verified after the 2026-11-14
deployment work.

- API image: `avelren-api:source-timing-20261114-v3`
- Collector image: `avelren-collector:source-timing-20261114-v4`
- Collector source commit: `6ba462b5ed9341270d552626b8af1039813ec721`
- API source commit: `0f4e1f6c50cbd49926d36bdd3bf35a3136c21258`
- Backup remote: `gdrive-crypt:avelren`
- Backup result verified: `paired_backup_verified`

The backup retention path treats failure to delete an old remote artifact as a
non-fatal retention warning. Creation, upload, manifest, checksum, and remote
read verification remain fail-closed.



## Phone verification

- Package: `ua.avelren.app`
- Installed version: `0.1.4` (`versionCode=8`)
- Last update observed: `2026-11-04 15:13:57`
- Source baseline identified in the local Git bundle: `5b8d0c23c765751295e2a44e6b7c3d60634f1e55`
- ADB device was online during verification; APK contents were not modified.
