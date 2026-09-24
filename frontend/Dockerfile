FROM node:20-slim AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
# Railway injects $PORT. BACKEND_URL (백엔드 공개 URL)은 컨테이너 부팅 시
# env.js로 주입 — 백엔드 주소가 바뀌어도 프론트 재빌드 없이 반영됨.
CMD ["sh", "-c", "echo \"window.__BACKEND_URL__=\\\"${BACKEND_URL:-}\\\";\" > /usr/share/nginx/html/env.js; sed -i -E \"s/listen +[^;]*;/listen ${PORT:-80};/g\" /etc/nginx/conf.d/default.conf; nginx -g 'daemon off;'"]
