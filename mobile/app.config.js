// app.json을 그대로 쓰고, 안드로이드 알림(Firebase) 설정 파일만 덧붙인다.
// google-services.json은 저장소에 올리지 않는다: EAS 빌드는 환경 변수 GOOGLE_SERVICES_JSON(파일)로 받고,
// 내 컴퓨터에서 빌드할 땐 mobile/google-services.json에 두면 된다.
const fs = require('fs');
const path = require('path');

module.exports = ({ config }) => {
  const file = process.env.GOOGLE_SERVICES_JSON || (fs.existsSync(path.join(__dirname, 'google-services.json')) ? './google-services.json' : undefined);
  return file ? { ...config, android: { ...config.android, googleServicesFile: file } } : config;
};
