import { state } from '../ghost/core/state.js';

export function appendAgentDecisions(result) {
    for (const event of result?.agent_events || []) {
        if (state.chatHistory.some(message => message.messageId === event.id)) continue;
        const content = event.status === 'rejected' ? `动作未执行：${event.reason || ''}` : event.text;
        if (!content) continue;
        const saved = result.conversation?.agents?.find(message => message.message_id === event.id);
        state.addChatMessage({ role: 'assistant', speaker: event.npc_name, content,
            timestamp: Date.now(), isDialogue: state.currentDialogueNPC?.id === event.actor_id,
            canonicalDecision: true, messageId: event.id, conversationIndex: saved?.message_index,
            rewriteCandidates: [], isStreaming: false });
    }
}
