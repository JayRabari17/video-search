import React, { useState } from 'react';
import Sidebar from './components/Sidebar';
import SearchBar from './components/SearchBar';
import ResultsGrid from './components/ResultsGrid';
import VideoPlayer from './components/VideoPlayer';
import VideoUpload from './components/VideoUpload';
import VideoExplore from './components/VideoExplore';
import SearchMarengo3 from './components/SearchMarengo3';
import LoginScreen from './components/LoginScreen.jsx';
import { searchClips, searchClipsWithImage } from './services/api';
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { getLoggedInEmail, isLoggedIn, logout, setLoggedIn } from './auth/loginSession.js';

function LandingPage({ userEmail, onLogout }) {
  const [currentPage, setCurrentPage] = useState('search-3');
  const [clips, setClips] = useState([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedClip, setSelectedClip] = useState(null);
  const [hasSearched, setHasSearched] = useState(false);

  const handle_search = async (searchQuery, searchType, topK = 20, imageResponse = null, imageFile = null) => {
    setIsLoading(true);
    setError(null);
    setQuery(searchQuery || '');
    setHasSearched(true);
    try {
      if (imageResponse) {
        setClips(imageResponse.clips);
        setTotal(imageResponse.total);
      } else if (imageFile) {
        const response = await searchClipsWithImage(imageFile, topK, searchType);
        setClips(response.clips);
        setTotal(response.total);
      } else {
        const response = await searchClips(searchQuery, topK, searchType);
        setClips(response.clips);
        setTotal(response.total);
      }
    } catch (err) {
      setError('Failed to search videos. Please try again.');
      console.error('Search error:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const handle_clip_click = (clip) => setSelectedClip(clip);
  const close_player = () => setSelectedClip(null);

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-blue-50">
      <Sidebar
        activeTab={currentPage}
        setActiveTab={setCurrentPage}
        userEmail={userEmail}
        showLogout={true}
        onLogout={onLogout}
      />
      <main className="ml-20 flex flex-col items-center min-h-screen min-w-0 px-4 sm:px-6 lg:px-8 py-8 sm:py-12">
        {currentPage === 'upload' ? (
          <VideoUpload />
        ) : currentPage === 'explore' ? (
          <VideoExplore />
        ) : currentPage === 'search-3' ? (
          <SearchMarengo3 />
        ) : (
          <SearchMarengo3 />
        )}
      </main>
      {selectedClip && (
        <VideoPlayer clip={selectedClip} onClose={close_player} />
      )}
    </div>
  );
}

function LoginRoute() {
  const navigate = useNavigate();
  if (isLoggedIn()) {
    return <Navigate to="/" replace />;
  }
  return (
    <LoginScreen
      onContinue={(user) => {
        setLoggedIn(
          user?.user?.username || user?.user?.email || user?.username || user?.email,
          user?.access_token
        );
        navigate('/', { replace: true });
      }}
    />
  );
}

function ProtectedLandingRoute() {
  const navigate = useNavigate();
  if (!isLoggedIn()) {
    return <Navigate to="/login" replace />;
  }
  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };
  return <LandingPage userEmail={getLoggedInEmail()} onLogout={handleLogout} />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginRoute />} />
      <Route path="/" element={<ProtectedLandingRoute />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
