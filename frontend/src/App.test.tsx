import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import messages from "../../src/hmanga/locales/zh-CN.json";
import App from "./App";

describe("App", () => {
  it("renders the localized pairing heading", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
    render(
      <QueryClientProvider client={new QueryClient()}>
        <App />
      </QueryClientProvider>,
    );
    expect(
      screen.getByRole("heading", { name: messages["label.connect_app"] }),
    ).toBeInTheDocument();
  });
});
