# FCM ownership і Android recovery — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Закрити переприв’язування чужого FCM token, зберігши credentials/subscriptions чинного пристрою й безпечне відновлення власного push після конфлікту.

**Architecture:** API серіалізує claim непорожнього token під transaction-scoped candidate lock, не від’єднує чужого власника й повертає typed409. Android використовує один coordinator і durable generation/rotation state, окремо від installation identity. Provider rotation і UI/status підключаються після незалежного приймання state machine.

**Tech Stack:** FastAPI/psycopg/PostgreSQL16; Kotlin/coroutines/EncryptedSharedPreferences/WorkManager; чинний Firebase BOM33.7.0, JVM/Ktor MockEngine, isolated PostgreSQL.

**Spec:** [Погоджена специфікація](../specs/2026-10-12-fcm-token-ownership-design.md), коміт ae6f395. Власник погодив12.10: «Погоджую специфікацію; готуй план».

Статус: план для перегляду перед implementation. Виконання — окремі агенти/fresh task reviews і whole-branch review, як раніше погоджено. Notifier compare-and-clear — окремий PR, не повторювати. Початковий main eed0cb0; перед execution звірити latestmain та notifier integration. Жодних production/SDK/Play операцій цей план не дозволяє.

## Global Constraints

- POST вільний/відсутній token →201/new credentials; зайнятий →409 detail.code=fcm_token_conflict без нової installation і без зміни owner.
- PUT спочатку authentication; вільний/власний token →200, чужий →409; при конфлікті збережені обидва devices, credentials/capabilities/subscriptions/Admin.
- 401 credential failure окремо від409; token не credential і не дозволяє відновити чужі subscriptions.
- No UPDATE that strips another owner's token; no applied migrations changes. Чинний UNIQUE(fcm_token) — final invariant.
- Тільки одна завершена automatic rotation на durable incident; повторний replacement conflict →conflict_blocked, не нескінченний delete/POST цикл.
- Valid credentials на PUT409 не очищуються. Lost secret уже зараз дає new installation без доступу до старих subscriptions/Admin; цей contract збережено.
- Durable generation/phase CAS, enqueue-before-HTTP, cancellation propagation; Worker не REPLACE самого себе під час internal recovery.
- No secret/token/owner ID у public409/logs/exception traces; PostgreSQL parameter/error logging окремо перевіряється до deployment.
- No Firebase SDK/FID migration: BOM33.7.0, deleteToken()/getToken() adapter; no liveFCM/єЧерга у tests.
- Prepared API+APK, API-first deployment лише за окремимGO; старий APK може не відновити conflict до оновлення; no insecure server fallback.
- Source/CI/merge/APIdeploy/APKhash/phone/Play — окремі evidence gates.

## Review Focus

1. DELETE/secret change між authentication і token UPDATE:401, не200; no foreign data leakage (Task1).
2. Lost POST response створив orphan: bounded rotation/new identity, не exactly-once claim чи stolen credentials (Task3).
3. Process death/commit failure після deleteToken: durable budget, no repeated destructive rotations (Task2/3).
4. Callback oldX/worker cancellation REPLACE під час newY: generation CAS і canonical provider token, pendingY notcleared (Task3/4).
5. Server409 vs unrelated409/503 і oldAPK: typed conflict only, no credential wipe, accurate rollout/status (Task4/5).

## File structure і interfaces

Task1 owns серверні mutations і categorical logging. Tasks2–3 додають незалежні Android ports/state/coordinator; actual existing repository/provider wiring належитьTask4, тому попередні tasks не оголошують recovery deployed.

New FcmRecoveryContracts.kt: enum RecoveryPhase {PENDING, ROTATION_REQUESTED, ROTATED, ATTACHING, CONFLICT_BLOCKED}; RecoveryRecord(formatVersion: Int, revision: Long, incidentId: String, generation: Long, phase: RecoveryPhase, candidateToken: String?, rotationSourceToken: String?, completedRotations: Int). Version1; revision/generation positiveLong; UUID incident; completedRotations0..1; toString redacted. Strict phase-field validation; unknown/corrupt state remainsblocked, not silently reset.

RecoveryStore suspend load(): RecoveryRecord?; suspend compareAndSet(expected: RecoveryRecord?, replacement: RecoveryRecord?): Boolean. CAS compares full revision/phase/generation, not raw token alone. CredentialCommitter suspend commit(expected: DeviceStore.Credentials?, replacement: DeviceStore.Credentials?): Boolean with real acknowledged encrypted preferences commit, preserving otherkeys. RotatingTokenSource suspend currentToken(): String; suspend deleteCurrentToken(): Unit. RecoveryApi suspend register(token: String): Credentials; suspend update(creds: Credentials, token: String): Unit; fun isStale(error: Throwable): Boolean; fun isTokenConflict(error: Throwable): Boolean. PushSyncState = Pending/Synced/Retrying/ConflictBlocked/StorageFailed; no secrets in states.

FcmRecoveryCoordinator(api: RecoveryApi, credentials: () -> Credentials?, committer: CredentialCommitter, records: RecoveryStore, tokens: RotatingTokenSource, scheduler: FcmTokenRetryScheduler): state: StateFlow<InstallationState>, pushState: StateFlow<PushSyncState>, suspend initialize(), suspend providerSignal(), suspend syncOnce(): PendingTokenSyncOutcome, suspend authenticatedCall<T>(block: suspend (Credentials) -> T): T. One defined mutation gate; no opposite nestedmutex order. New coordinator exposes same authenticated contract; installation Ready and push readiness are separate.

Команди gradlew.bat нижче виконуються з apps/android; backend/runner commands — з repo root.

### Task 1: Server token ownership і real API/PostgreSQL races

**Files:** Modify services/backend/src/avelren/subscriptions_api.py, services/backend/src/avelren/api.py, services/backend/tests/database/api/test_auth.py; Create services/backend/tests/database/api/test_token_ownership.py; Update docs/API-PROVENANCE.json і docs/CORE-PROVENANCE.json affected revision metadata only, retained originalhash/notes.

**Interfaces:** Existing POST/PUT response schemas unchanged forsuccess. Internal _lock_token_candidate(conn: AsyncConnection, token: str) -> None; _token_owner(conn: AsyncConnection, token: str) -> str | None. Transaction-scoped pg_advisory_xact_lock on signed64bit prefix of SHA256(namespace+token), namespace avelren-fcm-token-v1; never rawtoken askey. Claim lock before own device UPDATE/rowlock. No multiple token locks, UNIQUE finalguard.

- [ ] **Step1: Write failing tests** test_post_preserves_owner, test_put_preserves_both_devices, test_own_or_free_token_success, test_deleted_after_auth401, test_two_posts_one_owner, test_post_vs_put, test_two_puts_no_deadlock, test_no_secret_diagnostics. Assertions201/200/409 exacttypedbody; no owner/null/capability/subscription/Admin changes; invalidcredentials401 first; deletedrow never200.
- [ ] **Step2: RED** named API subset in owned runner: bash scripts/test_database.sh api. Barrier-controlled parallel TestClient requests/separate actualDBconnections under avelren_api, no synthetic SQL models replacing real API.
- [ ] **Step3: Implement** sametransaction candidate lock→owner check→INSERT/UPDATE RETURNING→capabilities; POST ON CONFLICT DO NOTHING guards noncooperating race. PUT catches only exact token UniqueViolation after savepoint/rollback, not allintegrity failures; missing updated row401. Bound lockwait by existingAPI timeout; timeout503. Remove dangerous comments/token-transfer; typed409 noidentity. Sanitize API OperationalError log to class/SQLSTATE, never exc/params; no global authrefactor.
- [ ] **Step4: GREEN** focused/API suite once, auth/capabilities/Admin regressions and nuisance unrelatedintegrityerror propagation. Exactrace ownsone token, no unhandled500. Capturepublic/applogs secretabsence; docs explicitly do not claim PostgreSQLserverlogs validated. Ruff/provenance after affectedsource changes.
- [ ] **Step5: Commit** namedfiles/tests/metadata, fresh review; production unchanged.

### Task 2: Durable recovery records і confirmed credential writes

**Files:** Create apps/android/app/src/main/java/ua/avelren/app/data/FcmRecoveryContracts.kt, FcmRecoveryStore.kt; Modify DeviceStore.kt; Create apps/android/app/src/test/java/ua/avelren/app/data/FcmRecoveryStoreTest.kt.

**Interfaces:** Produces contracts above and DeviceRecoveryStore implementing RecoveryStore/CredentialCommitter against existing encryptedpreferences. Existing saveCredentials/clearCredentials remaincompatible untilTask4 wiring; new methods commitCredentialsIfMatches(expected: Credentials?, replacement: Credentials?) -> Boolean and recovery CAS helpers use one defined preferences lock.

- [ ] **Step1: Write failing tests** test_legacy_pending_migration_atomic, test_revision_cas_no_newer_clear, test_commit_failure_preserves_record, test_credential_commit_before_ready, test_corrupt_phase_blocked, test_completed_rotation_budget_persists. Assert oneatomic migration of pending_fcm_token toversion1, no permissions/onboardingkeys changed; no secret representation.
- [ ] **Step2: RED** gradlew.bat -PavelrenUiPreview=true :app:testDebugUnitTest --tests ua.avelren.app.data.FcmRecoveryStoreTest --no-daemon --max-workers=2. Use test preferences port with actual CAS/serialization, no Androidplatform-global mocking.
- [ ] **Step3: Implement** strictrecordformat/phasefields; encryptedprefs.commit acknowledgement; full-record CAS; preserve pending on failedsave/migration, reject invalidstate without resetbudget. Generation overflow refuses. Identity CAS includes exact currentpair, no overwriting parallel validcredentials. No plaintext files/logs.
- [ ] **Step4: GREEN** samefocused tests plus existing DeviceStore/pending token cases; phase/cas/recreation evidence, notfakecounteronly.
- [ ] **Step5: Commit** contracts/store/tests, fresh review; runtime notwired yet.

### Task 3: Single coordinator і bounded rotation/recovery

**Files:** Create apps/android/app/src/main/java/ua/avelren/app/data/FcmRecoveryCoordinator.kt; Create apps/android/app/src/test/java/ua/avelren/app/data/FcmRecoveryCoordinatorTest.kt.

**Interfaces:** Consumes Task2ports/records and produces coordinator above. Existing InstallationRepository contract remains unchanged untilTask4. Coordinator uses atomicCredentialCommitter; recordgeneration androtationbudget acrossstartup/workerretry.

- [ ] **Step1: Write failing tests** test_put409_preserves_creds, test_lost_post_response, test_rotation_once_then_blocked, test_resume_all_phases, test_delete_timeout_provider_changed, test_callback_x_during_y, test_parallel401_conflict, test_second401_no_loop, test_failed_commit_no_ready, test_newer_pending_not_cleared. Suspension/barriers assert repository outcomes and exact durable states, no sleeps.
- [ ] **Step2: RED** gradlew.bat -PavelrenUiPreview=true :app:testDebugUnitTest --tests ua.avelren.app.data.FcmRecoveryCoordinatorTest --no-daemon --max-workers=2.
- [ ] **Step3: Implement** providerSignal durablehandoff beforeenqueue/HTTP; current SDKtoken canonical before attach, oldcallback hintnotauthority. Confirm ROTATION_REQUESTED beforedelete; afterambiguousdelete rereadprovider, replacementdifferentfromsource records ROTATED/completed1 beforeattach. Outagefetch retries with existingbackoff, not repeateddelete. ValidPUT409 keepsidentity; POST/confirmed401 createsnewpair and commit-beforeReady. LostPOST maycreateorphan, boundedreplacement/newidentity not recovery of unknownsecret.
- [ ] **Step4: GREEN** allnamed tests; internalworker nevercallsREPLACE onitself; cancellation propagated withoutclearingrecord. CAS preventsoldinflightresult credentialpublish/recordclear. Replacementconflict withbudget1 visibleConflictBlocked; user/newprovidertoken canattemptsync but cannotresetbudget untilsuccess. Original authenticatedrequest repeated atmostonce after401recovery.
- [ ] **Step5: Commit** coordinator/tests, fresh review; no liveFirebase.

### Task 4: Ktor/Firebase provider, existing repository/worker і visible status

**Files:** Modify apps/android/app/src/main/java/ua/avelren/app/data/Api.kt, InstallationRepository.kt, FcmTokenRetry.kt, FcmTokenSyncWorker.kt, AvelRenApp.kt (at app package, not data), ui/AvelRenScreen.kt; Modify existing InstallationRepositoryTest.kt; Create tests/data/FcmConflictApiTest.kt, tests/data/FcmRecoveryWiringTest.kt at full apps/android/app/src/test/java/ua/avelren/app/ paths.

**Interfaces:** Api.registerDevice/updateToken translate only409/detail.code=fcm_token_conflict into new TokenConflictException withoutrawresponse; existing401 classifier retained. AvelRenApp binds RotatingTokenSource to FirebaseMessaging.deleteToken().await()/token.await(), existingBOM33.7.0; no FirebaseInstallations deletion/SDKupgrade. InstallationRepository delegates mutations/authcalls/state to Task3coordinator, keeps publiccallerscompatible, exposes pushState. Existing worker uses coordinator sync outcome; no schedulerREPLACE duringinternalrotation.

- [ ] **Step1: Write failing tests** test_only_typed409_rotates, test_unrelated409_terminal, test_503_retry_pending, test_real_repository_delegation, test_worker_does_not_cancel_self, test_pendingY_afterX_success, test_valid_creds_stay_ready_pushblocked, test_sdk_adapter_compile. MockEngine capturessecretfreecodedexception; fakeFirebaseport only.
- [ ] **Step2: RED** gradlew.bat -PavelrenUiPreview=true :app:testDebugUnitTest --tests ua.avelren.app.data.FcmConflictApiTest --tests ua.avelren.app.data.FcmRecoveryWiringTest --no-daemon --max-workers=2.
- [ ] **Step3: Implement wiring:** replace oldparallelrecoverymutations, preserve queues/ACK/admin/notificationpermission/history. SDKcurrentreadback canonical; workerdrainnewgeneration orretry, neverfalseSynced. UI small Ukrainian pushstatus only whenpending/failed, no redesign. Exactstrings: «Синхронізуємо сповіщення…», «Сповіщення тимчасово недоступні. Спробуйте ще раз.»; retrybutton calls existingcoordinator providerSignal, not resetrotationbudget. No credential/tokentext in UI.
- [ ] **Step4: GREEN** focused+existing InstallationRepository tests, compileDebugKotlin, explicit adapter API compile underpinnedBOM. Checksource/jobworker concurrency controls and storagecommit ordering.
- [ ] **Step5: Commit** namedruntime/tests, fresh review; this enables source recovery but notphone/deploymentclaims.

### Task 5: Combined acceptance, provenance/docs та controlled integration

**Files:** Modify docs/RELEASE-READINESS.md, docs/MIGRATION-REMAINING.md, services/backend/README.md, apps/android/README.md, docs/ANDROID-PROVENANCE.json affectedrevisionsonly; Create docs/FCM-TOKEN-OWNERSHIP-2026-10-12.md. CI filters already include subscriptions_api.py/Android; modify only if actual newpaths missed. No new expensive unconditional workflow.

- [ ] **Step1: Combined tests** reinstall+lostsecret409→replacement201, restoredvalidcredentials409→PUT sameidentity; processdeath/offline/resume onallphases, nooldsubscriptions transfer; realAPI/PG concurrentclaims andJVMrepository states. TestsameAPKagainstlegacyAPI successpath compatibility andnewAPItyped409; noinsecurefallback.
- [ ] **Step2: RED** beforefinalwiring wherecoveragegapfound, thenminimalfix belongsowningoriginalimplementer; noimplementerhelperagents.
- [ ] **Step3: GREEN** completeAPI/defaultDB relevant suites, fullbackendunit andAndroidJVM/compile/lint oncefinalsource; Ruff/provenance/CIscopes/diff. Existingnotifier14regressions includeddefaultDB. No liveFCM/phonekeyrequests, no productdependencyinstall toforce tests.
- [ ] **Step4: Docs/provenance** retainedoriginalsourcehashes/previousnotes; exactheads/counts andknownwarnings; no guaranteedexactlyonceorFirebase deliveryclaims. RecordAPIfirstrollout, oldAPKconflictlimitation, availableupdatechannelnotrelyingonpush; PostgreSQLlogging check, freshschema/images/backup andacceptedrollbackbefore separateGO. Androidexisting0.1.3release remainsunpublished untilphone/Playgates.
- [ ] **Step5: Commit/review/integrate** freshalltaskreviews+mostcapablewholebranchreview, blockersfixed/scopedrereview; PRattached, exact-headrelevantCI, mergeverified. No billingincrease/privatevisibilitychange/productiondeployment/APKinstall/Playpublish. Actions$3budget retained.

## Completion and self-review

- [ ] Allfive taskdeliverables/reviews, realPG andactualJVM tests; exact-headCI+mergeproof.
- [ ] Serverownerpreserved, credentialsstable, durablebudget/generation, typederrors, cancellation/workerordering andvisiblepushstate allcovered.
- [ ] Source/APIdeploy/APK/phone/Play statuses separate; operationalGO notinferred.
- [ ] No appliedmigration edits/adminprivilegechanges/accountsystem/secrettransfer.

Coverage map: server/conflict/timeout/authrace Task1; persistence/migration/budget Task2; recovery/concurrency/lostresponse Task3; canonicalcallback/Ktor/provider/worker/UI Task4; compatibility/docs/CI Task5. Specdependencies named; ports introducedTask2 beforeTask3; no cyclicruntimeimports. Tasks2/3 independentlycompile because they add newports/coordinator without existingrepository rewiring. Task4 owns integration. Proposedtestcommands use exactclasses; Android Gradle runs fromapps/android (notrepo root), Windows/Linux launcher chosenforruntime.
