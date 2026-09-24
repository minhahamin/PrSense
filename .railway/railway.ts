import { defineRailway, github, postgres, project, service, volume } from "railway/iac";

export default defineRailway(() => {
  const Postgres = postgres("Postgres");
  const chromaData = volume("chroma-data", { sizeMB: 1000 });

  const backend = service("backend", {
    source: github("minhahamin/PrSense", { branch: "main", rootDirectory: "backend" }),
    build: { builder: "DOCKERFILE" },
    healthcheckPath: "/health",
    healthcheckTimeout: 300,
    variables: {
      DATABASE_URL: Postgres.env.DATABASE_URL,
      CHROMA_DIR: "/data/chroma",
      MOCK_LLM: "false",
      // --- 시크릿은 IaC에 커밋하지 않음. 배포 후 아래 CLI로 설정 ---
      // railway variables --service backend --set OPENAI_API_KEY=sk-...
      // railway variables --service backend --set GITHUB_TOKEN=ghp_...
      // railway variables --service backend --set GITHUB_WEBHOOK_SECRET=...
      // railway variables --service backend --set FRONTEND_ORIGIN=<prsenseApp 공개 URL>
    },
    volumeMounts: { "chroma-data": { mountPath: "/data" } },
  });

  const frontend = service("prsenseApp", {
    source: github("minhahamin/PrSense", { branch: "main", rootDirectory: "frontend" }),
    build: { builder: "DOCKERFILE" },
    healthcheckPath: "/",
    healthcheckTimeout: 120,
    variables: {
      // backend 공개 도메인 생성 후 기입 (재빌드 불필요, 컨테이너 재시작만):
      // railway variables --service prsenseApp --set BACKEND_URL=https://<backend>.up.railway.app
      BACKEND_URL: "",
    },
  });

  return project("prsense", {
    resources: [Postgres, chromaData, backend, frontend],
  });
});
