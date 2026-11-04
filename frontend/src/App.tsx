// Routes for every screen. Role-only routes (school, review) also check the user's group.
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import Login from './pages/Login';
import Home from './pages/Home';
import NewCourse from './pages/NewCourse';
import Upload from './pages/Upload';
import SetChecks from './pages/SetChecks';
import AnalysisReport from './pages/AnalysisReport';
import EditStudio from './pages/EditStudio';
import Export from './pages/Export';
import SchoolConsole from './pages/SchoolConsole';
import ReviewConsole from './pages/ReviewConsole';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Home />} />
        <Route path="/courses/new" element={<NewCourse />} />
        <Route path="/courses/:code/upload" element={<Upload />} />
        <Route path="/courses/:code/checks" element={<SetChecks />} />
        <Route path="/analyses/:id" element={<AnalysisReport />} />
        <Route path="/analyses/:id/edit" element={<EditStudio />} />
        <Route path="/analyses/:id/export" element={<Export />} />
        <Route path="/school" element={<SchoolConsole />} />
        <Route path="/review" element={<ReviewConsole />} />
      </Routes>
    </BrowserRouter>
  );
}
