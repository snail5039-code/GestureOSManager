// src/api/controlClient.js
import axios from "axios";
import { controlApiBaseURL, aiApiBaseURL } from "../runtime/endpoints";

export const controlApi = axios.create({
  baseURL: controlApiBaseURL(), // file:// => http://127.0.0.1:8080/api
  timeout: 8000,
  headers: { Accept: "application/json" },
});

export const aiApi = axios.create({
  baseURL: aiApiBaseURL(), // file:// => http://127.0.0.1:8080/api
  timeout: 20000,
  headers: { Accept: "application/json" },
});
