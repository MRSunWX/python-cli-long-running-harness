// 游戏变量
const canvas = document.getElementById('game-canvas');
const ctx = canvas.getContext('2d');
const scoreElement = document.getElementById('score');
const highScoreElement = document.getElementById('high-score');
const startBtn = document.getElementById('start-btn');
const pauseBtn = document.getElementById('pause-btn');
const restartBtn = document.getElementById('restart-btn');
const gameMessage = document.getElementById('game-message');
const difficultySelect = document.getElementById('difficulty');

// 游戏设置
const gridSize = 20;
const gridWidth = canvas.width / gridSize;
const gridHeight = canvas.height / gridSize;

// 游戏状态
let snake = [];
let food = {};
let direction = 'right';
let nextDirection = 'right';
let score = 0;
let highScore = localStorage.getItem('snakeHighScore') || 0;
let gameRunning = false;
let gameLoop;
let difficulty = 'medium'; // easy, medium, hard

// 初始化游戏
function initGame() {
    // 初始化蛇
    snake = [
        {x: 5, y: 10},
        {x: 4, y: 10},
        {x: 3, y: 10}
    ];
    
    // 生成食物
    generateFood();
    
    // 重置游戏状态
    score = 0;
    scoreElement.textContent = score;
    highScoreElement.textContent = highScore;
    direction = 'right';
    nextDirection = 'right';
    gameMessage.textContent = '';
    
    // 清除之前的定时器
    if (gameLoop) {
        clearInterval(gameLoop);
    }
}

// 生成食物
function generateFood() {
    food = {
        x: Math.floor(Math.random() * gridWidth),
        y: Math.floor(Math.random() * gridHeight)
    };
    
    // 确保食物不会生成在蛇身上
    for (let segment of snake) {
        if (segment.x === food.x && segment.y === food.y) {
            return generateFood();
        }
    }
}

// 绘制游戏
function draw() {
    // 清空画布
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    // 绘制蛇
    snake.forEach((segment, index) => {
        if (index === 0) {
            // 蛇头
            ctx.fillStyle = '#4CAF50';
        } else {
            // 蛇身
            ctx.fillStyle = '#8BC34A';
        }
        ctx.fillRect(segment.x * gridSize, segment.y * gridSize, gridSize, gridSize);
        
        // 添加边框
        ctx.strokeStyle = '#333';
        ctx.strokeRect(segment.x * gridSize, segment.y * gridSize, gridSize, gridSize);
    });
    
    // 绘制食物
    ctx.fillStyle = '#FF5252';
    ctx.fillRect(food.x * gridSize, food.y * gridSize, gridSize, gridSize);
    
    // 添加食物的边框
    ctx.strokeStyle = '#D32F2F';
    ctx.strokeRect(food.x * gridSize, food.y * gridSize, gridSize, gridSize);
}

// 更新游戏状态
function update() {
    // 更新方向
    direction = nextDirection;
    
    // 计算新的蛇头位置
    const head = {x: snake[0].x, y: snake[0].y};
    
    switch (direction) {
        case 'up':
            head.y--;
            break;
        case 'down':
            head.y++;
            break;
        case 'left':
            head.x--;
            break;
        case 'right':
            head.x++;
            break;
    }
    
    // 检查碰撞（墙壁）
    if (head.x < 0 || head.x >= gridWidth || head.y < 0 || head.y >= gridHeight) {
        gameOver();
        return;
    }
    
    // 检查碰撞（自身）
    for (let i = 0; i < snake.length; i++) {
        if (snake[i].x === head.x && snake[i].y === head.y) {
            gameOver();
            return;
        }
    }
    
    // 将新头部添加到蛇
    snake.unshift(head);
    
    // 检查是否吃到食物
    if (head.x === food.x && head.y === food.y) {
        // 增加得分
        score += 10;
        scoreElement.textContent = score;
        
        // 生成新食物
        generateFood();
    } else {
        // 如果没有吃到食物，移除蛇尾
        snake.pop();
    }
}

// 游戏主循环
function gameStep() {
    update();
    draw();
}

// 开始游戏
function startGame() {
    if (!gameRunning) {
        gameRunning = true;
        gameMessage.textContent = '';
        startBtn.disabled = true;
        
        // 根据难度设置游戏速度
        let speed = 150; // 默认中等速度
        switch (difficulty) {
            case 'easy':
                speed = 200;
                break;
            case 'medium':
                speed = 150;
                break;
            case 'hard':
                speed = 100;
                break;
        }
        
        gameLoop = setInterval(gameStep, speed);
    }
}

// 暂停游戏
function pauseGame() {
    if (gameRunning) {
        gameRunning = false;
        clearInterval(gameLoop);
        gameMessage.textContent = '游戏已暂停';
        startBtn.disabled = false;
    } else {
        startGame();
    }
}

// 重新开始游戏
function restartGame() {
    clearInterval(gameLoop);
    gameRunning = false;
    initGame();
    draw();
    startBtn.disabled = false;
    gameMessage.textContent = '';
}

// 游戏结束
function gameOver() {
    clearInterval(gameLoop);
    gameRunning = false;
    startBtn.disabled = false;
    
    // 更新最高分
    if (score > highScore) {
        highScore = score;
        localStorage.setItem('snakeHighScore', highScore);
        highScoreElement.textContent = highScore;
        gameMessage.textContent = `游戏结束！新最高分: ${highScore}`;
    } else {
        gameMessage.textContent = `游戏结束！得分: ${score}`;
    }
}

// 键盘控制
function handleKeydown(e) {
    switch (e.key) {
        case 'ArrowUp':
            if (direction !== 'down') nextDirection = 'up';
            break;
        case 'ArrowDown':
            if (direction !== 'up') nextDirection = 'down';
            break;
        case 'ArrowLeft':
            if (direction !== 'right') nextDirection = 'left';
            break;
        case 'ArrowRight':
            if (direction !== 'left') nextDirection = 'right';
            break;
        case ' ':
            if (gameRunning) {
                pauseGame();
            } else {
                startGame();
            }
            break;
    }
}

// 难度设置
function setDifficulty() {
    difficulty = difficultySelect.value;
}

// 事件监听器
startBtn.addEventListener('click', startGame);
pauseBtn.addEventListener('click', pauseGame);
restartBtn.addEventListener('click', restartGame);
difficultySelect.addEventListener('change', setDifficulty);
document.addEventListener('keydown', handleKeydown);

// 初始化游戏
initGame();
draw();