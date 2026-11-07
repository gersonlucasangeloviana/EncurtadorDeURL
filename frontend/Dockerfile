FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
ENV NGINX_ENVSUBST_FILTER="^(API_KEY|TRUSTED_PROXY_CIDR)$"
COPY nginx.conf /etc/nginx/templates/default.conf.template
