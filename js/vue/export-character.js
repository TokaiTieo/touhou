import { exportCharacter } from '../api.js';

export async function exportCharacterToPNG(characterId) {
    window.dispatchEvent(new CustomEvent('touhou:loading-start', {
        detail: { message: '正在导出角色记录...' }
    }));
    try {
        const characterData = await exportCharacter(characterId);
        const characterName = characterData.profile?.name || characterId;
        const pngBlob = await createPngWithTextData(
            JSON.stringify(characterData, null, 2),
            characterName
        );
        const url = URL.createObjectURL(pngBlob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `character_${characterName}.png`;
        link.click();
        URL.revokeObjectURL(url);
        window.dispatchEvent(new CustomEvent('touhou:toast', {
            detail: { message: `角色「${characterName}」已导出为 PNG`, type: 'success' }
        }));
    } catch (error) {
        window.dispatchEvent(new CustomEvent('touhou:toast', {
            detail: { message: `导出失败：${error.message}`, type: 'error' }
        }));
    } finally {
        window.dispatchEvent(new CustomEvent('touhou:loading-end'));
    }
}

async function createPngWithTextData(textData, characterName) {
    const canvas = document.createElement('canvas');
    canvas.width = 560;
    canvas.height = 280;
    const context = canvas.getContext('2d');
    context.fillStyle = '#171218';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = '#a92439';
    context.fillRect(0, 0, 18, canvas.height);
    context.strokeStyle = '#d1a24e';
    context.lineWidth = 2;
    context.strokeRect(32, 28, canvas.width - 62, canvas.height - 56);
    context.fillStyle = '#f2e7d6';
    context.font = 'bold 28px "Microsoft YaHei"';
    context.textAlign = 'left';
    context.fillText(characterName, 62, 106);
    context.fillStyle = '#d1a24e';
    context.font = '17px "Microsoft YaHei"';
    context.fillText('东方异变录 · 角色存档', 62, 148);
    context.fillStyle = '#9b8e86';
    context.font = '14px "Microsoft YaHei"';
    context.fillText('此图片包含可重新导入的完整角色数据', 62, 196);
    const pngBlob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
    return new Blob([
        await injectTextChunk(await pngBlob.arrayBuffer(), 'CharacterData', textData)
    ], { type: 'image/png' });
}

async function injectTextChunk(pngBuffer, keyword, text) {
    const encoder = new TextEncoder();
    const keywordBytes = encoder.encode(keyword);
    const textBytes = encoder.encode(text);
    const chunkData = new Uint8Array(keywordBytes.length + textBytes.length + 1);
    chunkData.set(keywordBytes, 0);
    chunkData[keywordBytes.length] = 0;
    chunkData.set(textBytes, keywordBytes.length + 1);
    const type = encoder.encode('tEXt');
    const chunk = new Uint8Array(chunkData.length + 12);
    const chunkView = new DataView(chunk.buffer);
    chunkView.setUint32(0, chunkData.length);
    chunk.set(type, 4);
    chunk.set(chunkData, 8);
    chunkView.setUint32(chunk.length - 4, calculateCRC32(type, chunkData));

    const source = new DataView(pngBuffer);
    let position = 8;
    let iendPosition = -1;
    while (position + 12 <= pngBuffer.byteLength) {
        const length = source.getUint32(position);
        const chunkType = new TextDecoder().decode(new Uint8Array(pngBuffer, position + 4, 4));
        if (chunkType === 'IEND') {
            iendPosition = position;
            break;
        }
        position += length + 12;
    }
    if (iendPosition < 0) throw new Error('PNG 数据不完整');
    const result = new Uint8Array(pngBuffer.byteLength + chunk.length);
    result.set(new Uint8Array(pngBuffer, 0, iendPosition), 0);
    result.set(chunk, iendPosition);
    result.set(new Uint8Array(pngBuffer, iendPosition), iendPosition + chunk.length);
    return result;
}

function calculateCRC32(type, data) {
    const table = crcTable();
    let crc = 0xFFFFFFFF;
    for (const value of type) crc = table[(crc ^ value) & 0xFF] ^ (crc >>> 8);
    for (const value of data) crc = table[(crc ^ value) & 0xFF] ^ (crc >>> 8);
    return (crc ^ 0xFFFFFFFF) >>> 0;
}

function crcTable() {
    return Array.from({ length: 256 }, (_, index) => {
        let value = index;
        for (let bit = 0; bit < 8; bit += 1) {
            value = (value & 1) ? (0xEDB88320 ^ (value >>> 1)) : (value >>> 1);
        }
        return value >>> 0;
    });
}
