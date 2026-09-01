// js/ghost/core/state.js
// 幽灵模式全局状态管理

import { reactive } from '../../vendor/vue.esm-browser.prod.js';

export const GhostState = reactive({
    // 当前会话
    currentSession: {
        characterId: null,
        profile: null,
        currentScene: null,
        conversationHistory: [],
        isDead: false,
        time: null,
        incidentState: {},
        resources: {},
        reputation: {},
        campaignState: {},
        onboarding: {},
        currentGoals: [],
        activeTasks: [],
        relationshipsMap: {},
        lastTurnSummary: null,
        playerState: {}
    },
    
    // 聊天历史
    chatHistory: [],
    
    // UI状态
    isWaitingForAI: false,
    isCreatingCharacter: false,
    isInDialogue: false,
    currentDialogueNPC: null,
    
    // 场景数据
    currentSceneNPCs: [],
    locationTree: [],
    
    // 任务数据
    tasks: {
        active: [],
        completed: []
    },
    
    // 临时数据
    tempCharacterInput: "",
    tempCharacterProfile: null,
    
    // 方法
    reset() {
        this.currentSession = {
            characterId: null,
            profile: null,
            currentScene: null,
            conversationHistory: [],
            isDead: false,
            time: null,
            incidentState: {},
            resources: {},
            reputation: {},
            campaignState: {},
            onboarding: {},
            currentGoals: [],
            activeTasks: [],
            relationshipsMap: {},
            lastTurnSummary: null,
            playerState: {}
        };
        this.chatHistory = [];
        this.isWaitingForAI = false;
        this.isInDialogue = false;
        this.currentDialogueNPC = null;
        this.currentSceneNPCs = [];
        this.locationTree = [];
        this.tempCharacterInput = "";
        this.tempCharacterProfile = null;
        this.resetTasks();
    },
    
    updateSession(data) {
        Object.assign(this.currentSession, data);
    },
    
    addChatMessage(msg) {
        this.chatHistory.push(msg);
        return this.chatHistory[this.chatHistory.length - 1];
    },
    
    clearChatHistory() {
        this.chatHistory = [];
    },
    
    // 任务相关方法
    updateTasks(tasksData) {
        this.tasks = {
            active: tasksData.active_tasks || [],
            completed: tasksData.completed_tasks || []
        };
    },

    updateRelationships(relationshipsMap) {
        this.currentSession.relationshipsMap = relationshipsMap || {};
    },

    setLastTurnSummary(summary) {
        this.currentSession.lastTurnSummary = summary;
    },
    
    resetTasks() {
        this.tasks = {
            active: [],
            completed: []
        };
    },
    
    addActiveTask(task) {
        this.tasks.active.push(task);
    },
    
    completeTask(taskId) {
        const index = this.tasks.active.findIndex(t => t.id === taskId);
        if (index !== -1) {
            const completedTask = this.tasks.active[index];
            completedTask.completed_at = new Date().toISOString();
            this.tasks.completed.push(completedTask);
            this.tasks.active.splice(index, 1);
        }
    },
    
    updateTaskDescription(taskId, newDescription) {
        const task = this.tasks.active.find(t => t.id === taskId);
        if (task) {
            task.description = newDescription;
        }
    }
});

// 导出单例
export const state = GhostState;
