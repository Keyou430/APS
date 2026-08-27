FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_API_BASE_URL=/api
ARG VITE_FEATURE_EXTERNAL_GUESTS=false
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_FEATURE_EXTERNAL_GUESTS=${VITE_FEATURE_EXTERNAL_GUESTS}

RUN npm run build

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
