FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
ARG AGENT_WEB_ALLOWED_FRAME_ANCESTORS="'self'"
ENV AGENT_WEB_ALLOWED_FRAME_ANCESTORS=${AGENT_WEB_ALLOWED_FRAME_ANCESTORS}
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3003
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/.next/standalone ./
EXPOSE 3003
CMD ["node", "server.js"]
