# Google · Facebook · X · Apple 로그인

2026-10-31. 연동 코드는 로컬 구현 상태다. Firebase 테스트 프로젝트와 웹앱 등록, Google 공급자 활성화는 완료했다. 앱 배포·실제 계정 로그인 검증은 아직이다.

## 구현
공식 Firebase Web SDK가 각 공급자 OAuth를 처리하고, 우리 서버는 Firebase ID 토큰의 서명·프로젝트 audience·issuer·만료·최근 인증 시각·허용된 공급자를 검증한 뒤 기존 HttpOnly 앱 세션을 발행한다. 비밀번호나 공급자 액세스 토큰은 앱 DB에 저장하지 않는다. Firebase 브라우저 인증은 메모리에서만 유지하며 앱 세션 교환 후 로그아웃한다. Firebase 설정이 없으면 기존 Google GIS 경로를 유지한다. 설정이 없는 공급자의 가짜 버튼은 표시하지 않는다.

Google은 검증된 Google 공급자 ID를 기존 계정 ID로 유지한다. 다른 공급자는 facebook:/twitter:/apple: 접두어로 분리한다. 이메일 기반 병합·자동 게스트 기록 이전·계정 연결 기능은 구현하지 않았다. Firebase 콘솔의 계정당 이메일 설정 및 공급자 간 연결 정책도 실제 계정으로 확인해야 한다. Firebase UID를 우리 계정 ID로 그대로 대체하지 않는다.

## 활성화에 필요한 설정
1. 소유한 Firebase 프로젝트에 Web 앱을 등록하고 Authentication에서 사용할 공급자를 활성화한다. 새 프로젝트 생성, 유료 플랜, 개발자 프로그램 가입은 이 작업에서 실행하지 않았다.
2. 앱 서버 환경 변수에 공개 Web 설정 `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN`, `FIREBASE_PROJECT_ID`를 등록한다. `FIREBASE_AUTH_PROVIDERS=google,facebook,twitter,apple` 중 실제 설정·승인이 끝난 공급자만 나열한다. 공급자 비밀키는 Firebase 콘솔에만 입력한다. 공개 API 키도 프로젝트별 API 제한을 확인한다.
3. Firebase Authorized domains에 사용할 테스트/정식 호스트를 등록한다. 공급자 앱에는 Firebase가 제시하는 `https://<authDomain>/__/auth/handler` 콜백 주소를 정확하게 등록한다. `PUBLIC_ORIGIN`은 실제 앱 HTTPS origin으로 설정한다. 테스트·정식 프로젝트 및 키 분리를 권장한다.
4. Google: Google 공급자를 설정한다. 기존 GIS와 병행 시 기존 OAuth 클라이언트와 계정 ID 보존을 확인한다.
5. Facebook: Meta 앱 ID/비밀키와 로그인 콜백을 Firebase 안내에 따라 설정한다. 개발자·테스터 외 일반 사용자 로그인은 앱 공개 상태와 필요한 검토를 확인한 뒤 활성화한다.
6. X(Twitter): Firebase Twitter 공급자용 API key/API secret 및 callback URL을 설정한다. 이 구현은 Firebase TwitterAuthProvider를 사용하므로 별도의 X OAuth2 client ID만으로 대체하지 않는다. 현재 앱 권한·접근 플랜·비용을 콘솔에서 확인하며 임의 결제하지 않는다.
7. Apple: Apple Developer Program에서 웹 Sign in with Apple을 구성하고 Services ID, Team ID, Key ID, private key를 Firebase에 설정한다. 유료 가입이 필요하면 사용자가 직접 결정한다. Apple 익명 이메일과 계정 연결 관련 동의 조건을 확인한다.

## 출시 전 확인
- 각 공급자의 실제 신규/재로그인, 취소, 팝업 차단, Safari/Chrome, iPhone 인앱 브라우저를 검증한다. 인앱 브라우저는 공급자가 차단할 수 있으므로 Safari/Chrome 안내를 제공한다. 자동 redirect fallback은 구현하지 않았다.
- Google 기존 전적 보존, 서로 다른 공급자의 같은 숫자 ID·같은 이메일을 구분하는지 확인한다. 기존 Google 인증 사용자를 Firebase로 옮기는 실제 계정 검증은 남았다.
- 계정 탈퇴·공급자 연결 해제·개인정보 처리방침·데이터 삭제 안내와 공급자 공개 요건을 마련한다. 이번 변경은 가입 활성화 완료나 앱스토어 출시 요건 충족을 의미하지 않는다.
- 앱 세션은 기존과 같이 30일이며 Firebase 측 계정 중지·토큰 철회가 이미 발급된 앱 세션을 자동 철회하지 않는다. 앱 내 로그아웃은 서버 세션을 철회한다. 운영자 강제 세션 철회 연동은 별도 작업이다.
- 외부 계정 설정/키가 없어 실제 로그인은 미검증. 단위/통합 검사는 공급자 모의 응답과 실제 RSA 서명 검증을 함께 사용한다.

## 공식 문서
- https://firebase.google.com/docs/auth/web/google-signin
- https://firebase.google.com/docs/auth/web/facebook-login
- https://firebase.google.com/docs/auth/web/twitter-login
- https://firebase.google.com/docs/auth/web/apple
- https://firebase.google.com/docs/auth/admin/verify-id-tokens

아이디어: 로그인 선택은 My Page에만 모아 게스트 대국 접근을 유지한다. 최초 화면에 네 개의 인증 버튼을 추가해 플레이 진입을 복잡하게 만들지 않는다.

## 검증 기록
Python 전체 144개 통과 후 Google nonce 재사용 회귀 검사 1개 추가·통과. 새 로그인 프런트엔드 모의 SDK 검사와 기존 화면 검사 통과. 실제 RSA 서명·잘못된 audience·서명 변조, 4개 공급자 ID 분리, nonce 동시 재사용, 차단된 공급자 및 origin을 검사했다. 기존 Google nonce 저장 값이 빈 dict일 때 재사용을 허용하던 조건도 `is not None`으로 수정했다. 공식 Firebase SDK 12.4.0의 app/auth CDN 파일은 HTTP 200 응답을 확인했다. 실제 외부 공급자 계정으로 성공한 증거를 대체하지 않는다.

## Firebase 실제 설정 진행
- 사용자 약관 동의 승인 후 `13GO Test Auth` 프로젝트(ID `go-test-auth`) 생성 완료. Spark 무료 요금제 확인. Analytics/Gemini/선택 개발자 프로그램 가입은 제외.
- 웹앱 `13GO Test Web` 등록 완료. Firebase Hosting 추가하지 않음. Google 공급자 `사용 설정됨` 확인. 로그인 공개 이름은 `13GO Test`.
- 인증 도메인은 기본 localhost/firebaseapp.com/web.app만 있는 상태. `thirteen-go-test.onrender.com`을 추가 양식에 입력했으나 아직 저장하지 않았다.
- 기본 계정 연결 정책은 동일 이메일 계정 연결. 공급자별 분리 정책 저장을 시도했으나 자동 승인 검토가 구체적인 보안 정책 변경 승인이 없다는 이유로 거부했다. 설정 변경은 적용되지 않은 것을 확인했으며 우회하지 않았다. 도메인 추가와 공급자별 분리 두 변경에 대해 사용자 승인을 받아야 한다.
- Render 테스트 서비스가 test-menu-v11 브랜치/무료 요금제/자동 배포 꺼짐인 것을 확인했다. 환경 변수는 아직 변경하지 않았고 새 코드는 배포하지 않았다. 정식 서비스는 변경하지 않았다.
- Facebook/X/Apple 공급자 앱 등록과 키 연결, 실제 로그인 검증은 남았다. 공개 Web 설정을 소스에 커밋하지 않았다.
