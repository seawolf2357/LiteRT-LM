FROM node:20-slim
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev express
COPY dist/ ./dist/
COPY server.js ./
EXPOSE 7860
CMD ["node", "server.js"]
