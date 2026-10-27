import { NavLink, Route, Routes } from "react-router-dom";
import SearchPage from "./pages/SearchPage";
import ProductPage from "./pages/ProductPage";
import MetricsPage from "./pages/MetricsPage";

function navClass({ isActive }: { isActive: boolean }) {
  return `rounded-md px-3 py-1.5 text-sm font-medium ${
    isActive ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-200"
  }`;
}

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <NavLink to="/" className="text-lg font-bold tracking-tight">
            Warp<span className="text-indigo-600">cart</span>
          </NavLink>
          <nav className="flex gap-1">
            <NavLink to="/" end className={navClass}>
              Search
            </NavLink>
            <NavLink to="/metrics" className={navClass}>
              Cache metrics
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Routes>
          <Route path="/" element={<SearchPage />} />
          <Route path="/products/:id" element={<ProductPage />} />
          <Route path="/metrics" element={<MetricsPage />} />
        </Routes>
      </main>
    </div>
  );
}
