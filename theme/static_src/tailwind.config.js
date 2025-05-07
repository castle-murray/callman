/**
 * This is a minimal config.
 *
 * If you need the full config, get it from here:
 * https://unpkg.com/browse/tailwindcss@latest/stubs/defaultConfig.stub.js
 */

module.exports = {
    darkMode: 'class',
    content: [
        /**
         * HTML. Paths to Django template files that will contain Tailwind CSS classes.
         */

        /*  Templates within theme app (<tailwind_app_name>/templates), e.g. base.html. */
        '../templates/**/*.html',

        /*
         * Main templates directory of the project (BASE_DIR/templates).
         * Adjust the following line to match your project structure.
         */
        '../../templates/**/*.html',

        /*
         * Templates in other django apps (BASE_DIR/<any_app_name>/templates).
         * Adjust the following line to match your project structure.
         */
        '../../**/templates/**/*.html',

        /**
         * JS: If you use Tailwind CSS in JavaScript, uncomment the following lines and make sure
         * patterns match your project structure.
         */
        /* JS 1: Ignore any JavaScript in node_modules folder. */
        // '!../../**/node_modules',
        /* JS 2: Process all JavaScript files in the project. */
        // '../../**/*.js',

        /**
         * Python: If you use Tailwind CSS classes in Python, uncomment the following line
         * and make sure the pattern below matches your project structure.
         */
        // '../../**/*.py'
    ],
    safelist: [
    'h-4',           // Checkbox height
    'w-4',           // Checkbox width
    'border-gray-300'
    ],
    theme: {
        extend: {
            colors: {
                // Light Mode
                'body-bg': '#f3f4f6',      // gray-100
                'card-bg': '#ffffff',      // white
                'cream-bg': '#fef9f5',     // cream (approximation)
                'conflict-green': '#dcfce7', // green-100
                'conflict-yellow': '#fefce8', // yellow-100
                'text-primary': '#1f2937', // gray-800
                'text-secondary': '#4b5563', // gray-600
                'text-tertiary': '#374151', // gray-700
                'text-heading': '#111827', // gray-900
                'text-slate': '#334155',  // slate-700
                'text-yellow': '#d97706', // yellow-600
                'text-green': '#16a34a',  // green-600
                'text-red': '#dc2626',    // red-600
                'text-blue': '#2563eb',   // blue-600
                'primary': '#3b82f6',     // blue-500
                'primary-hover': '#2563eb', // blue-600
                'success': '#22c55e',     // green-500
                'success-hover': '#16a34a', // green-600
                'danger': '#ef4444',      // red-500
                'danger-hover': '#dc2626', // red-600
                'secondary': '#6b7280',   // gray-500
                'secondary-hover': '#4b5563', // gray-600
                'purple': '#8b5cf6',      // purple-500
                'purple-hover': '#7c3aed', // purple-600
                'indigo': '#6366f1',      // indigo-500
                'indigo-hover': '#4f46e5', // indigo-600
                'teal': '#14b8a6',        // teal-500
                'teal-hover': '#0d9488',   // teal-600
                'yellow': '#eab308',      // yellow-500
                'yellow-hover': '#ca8a04', // yellow-600
                'border-light': '#d1d5db', // gray-300
                'text-available': '#1e40af', // Deep blue for available requests
                'bg-available': '#e0f2fe', // Light blue for available requests

                // Dark Mode
                'dark-body-bg': '#1f2937', // gray-900
                'dark-card-bg': '#0f172a', // gray-950
                'dark-header-bg': '#374151', // gray-800
                'dark-conflict-green': '#14532d', // green-900
                'dark-conflict-yellow': '#713f12', // yellow-900
                'dark-text-primary': '#E2E8F0', // slate-300
                'dark-text-secondary': '#7C8CA2', // slate-500
                'dark-text-tertiary': '#94A3B8', // slate-400
                'dark-text-yellow': '#facc15', // yellow-400
                'dark-text-green': '#22c55e', // green-400
                'dark-text-red': '#f87171',   // red-400
                'dark-text-blue': '#60a5fa',  // blue-400
                'dark-primary': '#1E40AF',    // blue-800
                'dark-primary-hover': '#1E3A8A', // blue-950
                'dark-success': '#166534',    // green-600
                'dark-success-hover': '#15803d', // green-700
                'dark-danger': '#991B1B',     // red-800
                'dark-danger-hover': '#7F1D1D', // red-900
                'dark-secondary': '#4b5563',  // gray-600
                'dark-secondary-hover': '#374151', // gray-700
                'dark-purple': '#7c3aed',     // purple-600
                'dark-purple-hover': '#6d28d9', // purple-700
                'dark-indigo': '#4f46e5',     // indigo-600
                'dark-indigo-hover': '#4338ca', // indigo-700
                'dark-teal': '#0d9488',       // teal-600
                'dark-teal-hover': '#0f766e', // teal-700
                'dark-yellow': '#ca8a04',     // yellow-600
                'dark-yellow-hover': '#a16207', // yellow-700
                'dark-border': '#4b5563',     // gray-600
                'dark-border-dark': '#374151', // gray-700
                'dark-shadow': '#374151',     // gray-700
                'dark-text-available': '#06b6d4', // Cyan for available requests
                'dark-bg-available': '#0891b2', // Darker Cyan for available requests
            },
            backgroundImage: {
                'filled-event-gradient': 'linear-gradient(to right, #f7fafc, #d1fae5)',
                'dark-filled-event-gradient': 'linear-gradient(to right, #1a202c, #185235)',
            },
        },
    },
    plugins: [
        /**
         * '@tailwindcss/forms' is the forms plugin that provides a minimal styling
         * for forms. If you don't like it or have own styling for forms,
         * comment the line below to disable '@tailwindcss/forms'.
         */
        require('@tailwindcss/forms'),
        require('@tailwindcss/typography'),
        require('@tailwindcss/aspect-ratio'),
    ],
}
