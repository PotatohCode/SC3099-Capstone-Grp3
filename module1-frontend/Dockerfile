FROM node:18-alpine

WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm install

# Copy application code
COPY . .

# Next.js inlines NEXT_PUBLIC_* vars into the client bundle at build time, so they
# must be passed as build args (docker-compose's `environment:` only reaches the
# container at runtime, too late for `next build`). See docker-compose.yml
# `frontend.build.args` and lib/config.ts.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_FACE_SERVICE_URL=http://localhost:8001
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_FACE_SERVICE_URL=$NEXT_PUBLIC_FACE_SERVICE_URL

# Build the application
RUN npm run build

# Expose port
EXPOSE 3000

# Run the application
CMD ["npm", "start"]
