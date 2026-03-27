import React from 'react';
import { Video, Sparkles, Search, Upload } from 'lucide-react';

const Header = ({ currentPage, onPageChange }) => {
  return (
    <header className="bg-white border-b border-gray-200 sticky top-0 z-40 backdrop-blur-lg bg-white/80">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-primary-600 to-primary-400 rounded-xl flex items-center justify-center shadow-lg">
              <Video size={24} className="text-white" />
            </div>
            <div>
              <h1 className="text-lg sm:text-xl font-bold text-gray-900">Video Search</h1>
              <p className="text-xs text-gray-500 flex items-center gap-1">
                <Sparkles size={12} />
                Search
              </p>
            </div>
          </div>

          <nav className="flex items-center gap-4">
            <button
              onClick={() => onPageChange('search')}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                currentPage === 'search'
                  ? 'bg-primary-100 text-primary-700'
                  : 'text-gray-700 hover:text-primary-600 hover:bg-gray-100'
              }`}
            >
              <Search size={18} />
              <span className="hidden sm:inline">Search</span>
            </button>
            <button
              onClick={() => onPageChange('upload')}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                currentPage === 'upload'
                  ? 'bg-primary-100 text-primary-700'
                  : 'text-gray-700 hover:text-primary-600 hover:bg-gray-100'
              }`}
            >
              <Upload size={18} />
              <span className="hidden sm:inline">Upload</span>
            </button>
          </nav>
        </div>
      </div>
    </header>
  );
};

export default Header;
