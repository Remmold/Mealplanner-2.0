# Vite inlines VITE_* from .env at BUILD time, so frontend/.env must be present
# in this build context (it's scp'd to the VM before building). The values are
# the public Supabase URL + anon key — safe to ship in the browser bundle.
FROM node:22-alpine AS build
WORKDIR /app
# Cap V8's heap so tsc+vite can't balloon past the 1GB VM's RAM+swap mid-build.
ENV NODE_OPTIONS=--max-old-space-size=512
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
