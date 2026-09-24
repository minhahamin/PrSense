import { BrowserRouter, Link, Route, Routes } from 'react-router-dom';
import PRDetailPage from './pages/PRDetail';
import PRList from './pages/PRList';
import './styles.css';

export default function App() {
  return (
    <BrowserRouter>
      <header className="topbar">
        <Link to="/" style={{ color: 'inherit', textDecoration: 'none' }}>
          <span className="logo">
            prsenseApp<span>.</span>
          </span>
        </Link>
        <span className="sub">PR auto-review agent · LangGraph + RAG</span>
      </header>
      <Routes>
        <Route path="/" element={<PRList />} />
        <Route path="/pr/:owner/:repo/:pr" element={<PRDetailPage />} />
      </Routes>
    </BrowserRouter>
  );
}
