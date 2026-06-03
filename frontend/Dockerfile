FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
RUN apk add --no-cache apache2-utils
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.d/10-mbk-basic-auth.sh /docker-entrypoint.d/10-mbk-basic-auth.sh
RUN chmod +x /docker-entrypoint.d/10-mbk-basic-auth.sh
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s CMD nginx -t >/dev/null 2>&1 || exit 1
