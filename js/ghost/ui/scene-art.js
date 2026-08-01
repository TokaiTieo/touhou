import { appUi } from '../../vue/app-store.js';

const SCENE_ART = [
    { terms: ['博丽神社'], url: '/static/static/hakurei-shrine-hero-v1.png' },
    { terms: ['人间之里'], url: '/static/static/scene-human-village-v1.png' },
    { terms: ['红魔馆'], url: '/static/static/scene-scarlet-mansion-v1.png' },
    { terms: ['雾雨魔法店'], url: '/static/static/scene-kirisame-shop-v1.png' },
    { terms: ['魔法之森'], url: '/static/static/scene-forest-magic-v1.png' },
    { terms: ['永远亭'], url: '/static/static/scene-eientei-v1.png' },
    { terms: ['白玉楼'], url: '/static/static/scene-hakugyokurou-v1.png' },
    { terms: ['守矢神社'], url: '/static/static/scene-moriya-shrine-v1.png' },
    { terms: ['地灵殿'], url: '/static/static/scene-chireiden-v1.png' },
    { terms: ['雾之湖'], url: '/static/static/scene-misty-lake-v1.png' },
    { terms: ['命莲寺'], url: '/static/static/scene-myouren-temple-v1.png' },
    { terms: ['妖怪之山'], url: '/static/static/scene-youkai-mountain-v1.png' },
    { terms: ['月之都'], url: '/static/static/scene-lunar-capital-v1.png' },
    { terms: ['地狱'], url: '/static/static/scene-hell-v1.png' },
    { terms: ['太阳花田'], url: '/static/static/scene-sunflower-field-v1.png' },
    { terms: ['神灵庙'], url: '/static/static/scene-divine-mausoleum-v1.png' },
    { terms: ['后户之国'], url: '/static/static/scene-backdoor-land-v1.png' },
    { terms: ['畜生界'], url: '/static/static/scene-animal-realm-v1.png' },
    { terms: ['虹龙洞集市', '虹龙洞'], url: '/static/static/scene-rainbow-market-v1.png' },
    { terms: ['梦境世界'], url: '/static/static/scene-dream-world-v1.png' }
];

export function getSceneArtwork(sceneName = '') {
    const match = SCENE_ART.find(item => item.terms.some(term => String(sceneName).includes(term)));
    return match?.url || '/static/static/hakurei-shrine-hero-v1.png';
}

export function applySceneArtwork(sceneName) {
    appUi.sceneArtwork = getSceneArtwork(sceneName);
}
