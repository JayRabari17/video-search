const JsonDisplay = ({ data }) => {
  const syntaxHighlight = (json) => {
    json = JSON.stringify(json, null, 2);
    json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    
    return json.replace(
      /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
      (match) => {
        let cls = 'text-orange-400'; // numbers
        if (/^"/.test(match)) {
          if (/:$/.test(match)) {
            cls = 'text-blue-400 font-semibold'; // keys
          } else {
            cls = 'text-green-400'; // strings
          }
        } else if (/true|false/.test(match)) {
          cls = 'text-purple-400'; // booleans
        } else if (/null/.test(match)) {
          cls = 'text-gray-400'; // null
        }
        return `<span class="${cls}">${match}</span>`;
      }
    );
  };

  const highlightBraces = (html) => {
    // Highlight curly braces and brackets
    return html
      .replace(/([{}])/g, '<span class="text-yellow-400 font-bold">$1</span>')
      .replace(/([[\]])/g, '<span class="text-yellow-400">$1</span>');
  };

  return (
    <div className="bg-gray-900 rounded-xl p-3 sm:p-6 h-full overflow-y-auto overflow-x-hidden">
      <pre 
        className="text-sm font-mono whitespace-pre-wrap break-words text-gray-300 leading-relaxed"
        dangerouslySetInnerHTML={{ __html: highlightBraces(syntaxHighlight(data)) }}
      />
    </div>
  );
};

export default JsonDisplay;