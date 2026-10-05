// The browser calls its own origin; Vite forwards API requests locally.
// This also avoids localhost/127.0.0.1 CORS mismatches during development.
export default {
  server:{
    port:5173,
    strictPort:true,
    proxy:{
      '/api':{target:'http://127.0.0.1:8000',changeOrigin:true},
      '/health':{target:'http://127.0.0.1:8000',changeOrigin:true},
    },
  },
};
