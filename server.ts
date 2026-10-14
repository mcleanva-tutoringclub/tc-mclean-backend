import express, { Request, Response } from "express";
import env from "./src/config/env";

const app = express();
const PORT = Number(env.PORT);

app.use(express.json());

app.get("/", (_req: Request, res: Response) => {
  res.json({ message: "Server is running", status: 200, date: new Date() });
});

app.listen(PORT, () => {
  console.log(`Server listening on http://localhost:${PORT}`);
});
