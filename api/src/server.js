// Insight API (stage 9): serves the frozen DuckDB snapshot produced by pipeline/snapshot.
import "dotenv/config";
import cors from "cors";
import express from "express";

const app = express();
app.use(cors());
app.use(express.json());

app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

const PORT = process.env.PORT || 4000;
app.listen(PORT, () => {
  console.log(`OAH Insight API listening on port ${PORT}`);
});
