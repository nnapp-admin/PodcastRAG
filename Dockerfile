# Frontend image (Vite dev server: the UI is a dev-time surface for this
# take-home; `npm run build` produces the production bundle when needed).
FROM node:22-alpine

ENV NODE_ENV=development
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm install --no-audit --no-fund

COPY . .

EXPOSE 8080
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "8080"]
