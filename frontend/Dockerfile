FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm install -g npm@11.6.2
RUN npm ci

COPY . .

ARG VITE_API_URL=/api
ARG VITE_ENABLE_DEV_LOGIN=false
ARG VITE_TELEGRAM_BOT_USERNAME=
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_ENABLE_DEV_LOGIN=$VITE_ENABLE_DEV_LOGIN
ENV VITE_TELEGRAM_BOT_USERNAME=$VITE_TELEGRAM_BOT_USERNAME

RUN npm run build

FROM nginx:1.27-alpine

COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html/admin

EXPOSE 80
