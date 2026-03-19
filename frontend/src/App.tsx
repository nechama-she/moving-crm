import { BrowserRouter, Routes, Route } from "react-router-dom";
import LeadsList from "./LeadsList";
import LeadDetail from "./LeadDetail";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LeadsList />} />
        <Route path="/leads/:leadId" element={<LeadDetail />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
