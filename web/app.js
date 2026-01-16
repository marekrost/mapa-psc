// Configuration - match config.py values
const CONFIG = {
    mapCenter: [15.3381, 49.7437],  // Czech Republic center [lon, lat]
    mapZoom: 7,
    tilesUrl: window.location.origin + window.location.pathname.replace(/\/[^/]*$/, '') + '/tiles/{z}/{x}/{y}.pbf',

    // Four-color palette (configurable - match config.py)
    colorPalette: [
        'rgb(255, 107, 107)',  // Red
        'rgb(78, 205, 196)',   // Teal
        'rgb(255, 195, 113)',  // Orange
        'rgb(162, 155, 254)',  // Purple
    ]
};

// Initialize map
const map = new maplibregl.Map({
    container: 'map',
    style: {
        version: 8,
        sources: {
            'osm': {
                type: 'raster',
                tiles: [
                    'https://a.tile.openstreetmap.org/{z}/{x}/{y}.png',
                    'https://b.tile.openstreetmap.org/{z}/{x}/{y}.png',
                    'https://c.tile.openstreetmap.org/{z}/{x}/{y}.png'
                ],
                tileSize: 256,
                attribution: '© OpenStreetMap contributors'
            },
            'psc': {
                type: 'vector',
                tiles: [CONFIG.tilesUrl],
                minzoom: 6,
                maxzoom: 14
            }
        },
        layers: [
            {
                id: 'osm-layer',
                type: 'raster',
                source: 'osm',
                minzoom: 0,
                maxzoom: 22
            }
        ]
    },
    center: CONFIG.mapCenter,
    zoom: CONFIG.mapZoom
});

// Add navigation controls
map.addControl(new maplibregl.NavigationControl(), 'top-right');

// Track hover state
let hoveredPscId = null;

// Wait for map to load
map.on('load', () => {
    // Add PSČ polygon layer with four-color styling
    map.addLayer({
        id: 'psc-fills',
        type: 'fill',
        source: 'psc',
        'source-layer': 'psc',
        paint: {
            'fill-color': [
                'case',
                ['==', ['get', 'color_index'], 0], CONFIG.colorPalette[0],
                ['==', ['get', 'color_index'], 1], CONFIG.colorPalette[1],
                ['==', ['get', 'color_index'], 2], CONFIG.colorPalette[2],
                ['==', ['get', 'color_index'], 3], CONFIG.colorPalette[3],
                CONFIG.colorPalette[0]  // Default
            ],
            'fill-opacity': [
                'case',
                ['boolean', ['feature-state', 'hover'], false],
                0.7,
                0.4
            ]
        }
    });

    // Add PSČ border layer
    map.addLayer({
        id: 'psc-borders',
        type: 'line',
        source: 'psc',
        'source-layer': 'psc',
        paint: {
            'line-color': [
                'case',
                ['boolean', ['feature-state', 'hover'], false],
                '#000000',
                '#333333'
            ],
            'line-width': [
                'case',
                ['boolean', ['feature-state', 'hover'], false],
                2.5,
                1
            ],
            'line-opacity': 0.8
        }
    });

    // Update legend with actual colors
    document.getElementById('color-0').style.backgroundColor = CONFIG.colorPalette[0];

    // Mouse move handler (with throttling for performance)
    let throttleTimeout = null;
    map.on('mousemove', 'psc-fills', (e) => {
        if (throttleTimeout) return;

        throttleTimeout = setTimeout(() => {
            throttleTimeout = null;
        }, 50);  // 50ms throttle

        if (e.features.length > 0) {
            // Update hover state
            if (hoveredPscId !== null) {
                map.setFeatureState(
                    { source: 'psc', sourceLayer: 'psc', id: hoveredPscId },
                    { hover: false }
                );
            }

            hoveredPscId = e.features[0].id;
            map.setFeatureState(
                { source: 'psc', sourceLayer: 'psc', id: hoveredPscId },
                { hover: true }
            );

            // Update info panel
            updateInfoPanel(e.features[0].properties);

            // Change cursor
            map.getCanvas().style.cursor = 'pointer';
        }
    });

    // Mouse leave handler
    map.on('mouseleave', 'psc-fills', () => {
        if (hoveredPscId !== null) {
            map.setFeatureState(
                { source: 'psc', sourceLayer: 'psc', id: hoveredPscId },
                { hover: false }
            );
        }
        hoveredPscId = null;
        map.getCanvas().style.cursor = '';
    });

    // Click handler
    map.on('click', 'psc-fills', (e) => {
        if (e.features.length > 0) {
            const props = e.features[0].properties;

            // Update info panel
            updateInfoPanel(props, true);

            // Fly to feature
            const bounds = new maplibregl.LngLatBounds();
            e.features[0].geometry.coordinates[0].forEach(coord => {
                bounds.extend(coord);
            });

            map.fitBounds(bounds, {
                padding: 100,
                maxZoom: 12
            });
        }
    });

    console.log('Map loaded successfully');
});

// Update info panel with PSČ details
function updateInfoPanel(properties, clicked = false) {
    const infoDiv = document.getElementById('psc-info');
    const codeEl = document.getElementById('psc-code');
    const detailsEl = document.getElementById('psc-details');

    infoDiv.classList.add('active');

    // Format PSČ with space (e.g., "123 45")
    const pscFormatted = properties.psc.replace(/(\d{3})(\d{2})/, '$1 $2');
    codeEl.textContent = `PSČ ${pscFormatted}`;

    // Build details
    const details = [];
    details.push(`Počet adres: ${properties.point_count?.toLocaleString('cs-CZ') || 'N/A'}`);

    if (properties.area_km2) {
        details.push(`Přibližná plocha: ${properties.area_km2.toLocaleString('cs-CZ', { minimumFractionDigits: 2 })} km²`);
    }

    if (properties.method) {
        const methodMap = {
            'buffer': 'Kruhový buffer (1 adresa)',
            'convex_hull': 'Konvexní obal (2-3 adresy)',
            'convex_hull_fallback': 'Konvexní obal (náhradní metoda)',
        };

        let methodText = properties.method;
        for (const [key, value] of Object.entries(methodMap)) {
            if (methodText.includes(key)) {
                methodText = value;
                break;
            }
        }
        if (methodText.startsWith('alpha_shape')) {
            methodText = 'Konkávní obal (Alpha Shape)';
        }

        details.push(`🔧 Metoda: ${methodText}`);
    }

    detailsEl.innerHTML = details.join('<br>');
}

// Handle map errors
let tile404WarningShown = false;
map.on('error', (e) => {
    // Suppress 404 tile errors - these are expected for sparse datasets
    // (tippecanoe only generates tiles where data exists)
    const is404Error =
        (e.error && e.error.status === 404) ||
        (e.error && e.error.message && e.error.message.includes('404')) ||
        (e.error && e.error.message && e.error.message.includes('File not found'));

    if (is404Error && e.sourceId === 'psc') {
        if (!tile404WarningShown) {
            console.log('ℹ️ Some tiles return 404 - this is normal for sparse datasets (only tiles with data are generated)');
            tile404WarningShown = true;
        }
        return;  // Suppress the error
    }

    // Log other errors
    console.error('Map error:', e);
});

// Log when tiles are loaded
map.on('data', (e) => {
    if (e.sourceId === 'psc' && e.isSourceLoaded) {
        console.log('PSČ tiles loaded');
    }
});

// Allow palette customization via console
window.updateColorPalette = (colors) => {
    if (!Array.isArray(colors) || colors.length !== 4) {
        console.error('Palette must be an array of 4 RGB color strings');
        console.log('Example: updateColorPalette(["rgb(255,0,0)", "rgb(0,255,0)", "rgb(0,0,255)", "rgb(255,255,0)"])');
        return;
    }

    CONFIG.colorPalette = colors;

    // Update map layer
    map.setPaintProperty('psc-fills', 'fill-color', [
        'case',
        ['==', ['get', 'color_index'], 0], colors[0],
        ['==', ['get', 'color_index'], 1], colors[1],
        ['==', ['get', 'color_index'], 2], colors[2],
        ['==', ['get', 'color_index'], 3], colors[3],
        colors[0]
    ]);

    // Update legend
    document.getElementById('color-0').style.backgroundColor = colors[0];

    console.log('Color palette updated!');
};

console.log('Mapa PSČ loaded. Use updateColorPalette(["color1", "color2", "color3", "color4"]) to customize colors.');
