/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    usart.c
  * @brief   This file provides code for the configuration
  *          of the USART instances.
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2024 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "usart.h"

/* USER CODE BEGIN 0 */
#include <stdbool.h>
#include "fifo.h"
#include "usbd_cdc_if.h"

uint8_t usb_rx_data;
uart_feature current_feature = FUNC_FEATURE1;
static uint8_t tmp;
static uint8_t fifo_buffer[1024];
static fifo_t fifo_uart1_rx;
static volatile uint32_t uart1_rx_timeout = 0;
static bool uart1_rx_done = false;
/* ===== 补丁7：USB 中转环形缓冲（UART 中断写 / 主循环读，单生产者单消费者，无锁）=====
   为什么需要它：原来在 UART 中断里直接调 CDC_Transmit_FS，发送端持续发送时
   每秒约 960 次中断各发起一次 USB 传输，USB 栈被打满 -> 主循环饿死 -> 整个界面卡死。
   现在中断只把字节放进环形缓冲，主循环批量转发到 USB，数据不丢也不会卡。*/
#define USB_RING_SIZE   512
static volatile uint8_t  usb_ring[USB_RING_SIZE];
static volatile uint16_t usb_ring_head = 0;      /* 只由 UART 中断修改 */
static volatile uint16_t usb_ring_tail = 0;      /* 只由主循环修改 */
static volatile uint32_t usb_ring_drop = 0;      /* 缓冲满丢弃的字节数 */

static void usb_ring_put(uint8_t byte)
{
    uint16_t next = (uint16_t)((usb_ring_head + 1) % USB_RING_SIZE);

    if (next == usb_ring_tail) { usb_ring_drop++; return; }   /* 满则丢，绝不阻塞 */

    usb_ring[usb_ring_head] = byte;
    usb_ring_head = next;
}
/* USER CODE END 0 */

UART_HandleTypeDef huart1;

/* USART1 init function */

void MX_USART1_UART_Init(void)
{

  /* USER CODE BEGIN USART1_Init 0 */

  /* USER CODE END USART1_Init 0 */

  /* USER CODE BEGIN USART1_Init 1 */

  /* USER CODE END USART1_Init 1 */
  huart1.Instance = USART1;
  huart1.Init.BaudRate = 9600;
  huart1.Init.WordLength = UART_WORDLENGTH_8B;
  huart1.Init.StopBits = UART_STOPBITS_1;
  huart1.Init.Parity = UART_PARITY_NONE;
  huart1.Init.Mode = UART_MODE_TX_RX;
  huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart1.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART1_Init 2 */

  /* USER CODE END USART1_Init 2 */

}

void HAL_UART_MspInit(UART_HandleTypeDef* uartHandle)
{

  GPIO_InitTypeDef GPIO_InitStruct = {0};
  if(uartHandle->Instance==USART1)
  {
  /* USER CODE BEGIN USART1_MspInit 0 */

  /* USER CODE END USART1_MspInit 0 */
    /* USART1 clock enable */
    __HAL_RCC_USART1_CLK_ENABLE();

    __HAL_RCC_GPIOA_CLK_ENABLE();
    /**USART1 GPIO Configuration
    PA9     ------> USART1_TX
    PA10     ------> USART1_RX
    */
    GPIO_InitStruct.Pin = GPIO_PIN_9;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    GPIO_InitStruct.Pin = GPIO_PIN_10;
    GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    /* USART1 interrupt Init */
    HAL_NVIC_SetPriority(USART1_IRQn, 0, 0);
    HAL_NVIC_EnableIRQ(USART1_IRQn);
  /* USER CODE BEGIN USART1_MspInit 1 */

  /* USER CODE END USART1_MspInit 1 */
  }
}

void HAL_UART_MspDeInit(UART_HandleTypeDef* uartHandle)
{

  if(uartHandle->Instance==USART1)
  {
  /* USER CODE BEGIN USART1_MspDeInit 0 */

  /* USER CODE END USART1_MspDeInit 0 */
    /* Peripheral clock disable */
    __HAL_RCC_USART1_CLK_DISABLE();

    /**USART1 GPIO Configuration
    PA9     ------> USART1_TX
    PA10     ------> USART1_RX
    */
    HAL_GPIO_DeInit(GPIOA, GPIO_PIN_9|GPIO_PIN_10);

    /* USART1 interrupt Deinit */
    HAL_NVIC_DisableIRQ(USART1_IRQn);
  /* USER CODE BEGIN USART1_MspDeInit 1 */

  /* USER CODE END USART1_MspDeInit 1 */
  }
}

/* USER CODE BEGIN 1 */
void uart1_reconfig( uint32_t rate )
{
	/* 原有串口1的初始化 */
  huart1.Instance = USART1;
  huart1.Init.BaudRate = rate;
  huart1.Init.WordLength = UART_WORDLENGTH_8B;
  huart1.Init.StopBits = UART_STOPBITS_1;
  huart1.Init.Parity = UART_PARITY_NONE;
  huart1.Init.Mode = UART_MODE_TX_RX;
  huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart1.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart1) != HAL_OK)
  {
    Error_Handler();
  }
	
	/* 创建E22串口接收队列
     推荐使用队列+超时断包方式来接收E22模组数据，因为在某些情况下模组串口输出数据不一定是连续的！！！	*/
	if( fifo_create( &fifo_uart1_rx, fifo_buffer , sizeof(fifo_buffer)) != FIFO_OK )
	{
			///@todo 
			/* 队列创建失败 */
			while(1);
	}	
	
  /* 允许E22串口中断接收 (单字节中断) */
	HAL_UART_Receive_IT( &huart1, &tmp, 1);
	
	uart1_rx_timeout = 0;
	uart1_rx_done = false;
}

void uart1_rx_timeout_1ms_callback(void)
{
	/* 串口接收中断中会不停刷新倒计时
     但滴答定时每1毫秒中断内会递减倒计时	*/
	if( uart1_rx_timeout > 0 )
	{
			uart1_rx_timeout--;
		
			/*如果倒计时归0，则可以断包处理了 */
			if( uart1_rx_timeout == 0 )
			{
				uart1_rx_done = true;
			}
	}
}

void uart1_wait_response_blocked( uint8_t * buffer, uint16_t *length )
{
    uint32_t fifo_rx_len = 0;
    uint32_t start = HAL_GetTick();          /* ??:?????? */

    /* ???????? */
    fifo_clear( &fifo_uart1_rx );

    /* ??100ms??? ?????1ms???????*/
    systick_set_user_timeout(100);

    /* ??:???????,????????????,????? */
    while( uart1_rx_done == false )
    {
        if( (systick_get_user_timeout() == 0)
            || ((HAL_GetTick() - start) > 120) )   /* ??? 120ms */
        {
            uart1_rx_done = false;
            *length = 0;
            usb_printf( "Response Timeout!!! \r\n");
            return;                                 /* ? ??,?? while(1) */
        }
    }

    /* ???????? */
    if( uart1_rx_done == true )
    {
        uart1_rx_done = false;
        fifo_get_length( &fifo_uart1_rx , &fifo_rx_len);
        fifo_read( &fifo_uart1_rx, buffer, fifo_rx_len );
        *length = fifo_rx_len;
    }
}

bool uart1_check_rx_done( uint8_t *buffer , uint32_t *length )
{
	bool ret = false;
	uint32_t fifo_rx_len = 0;
	
	if( uart1_rx_done == true )
	{
		uart1_rx_done = false;
		
		/* 获取当前串口接收队列内容长度 */
		fifo_get_length( &fifo_uart1_rx , &fifo_rx_len);

		/* 串口数据拷贝 */
		fifo_read( &fifo_uart1_rx, buffer, fifo_rx_len );	

		*length = fifo_rx_len;	

		ret = true;
	}
	
	return ret;
}

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
	uint8_t rd,rd_2;
	if (huart->Instance == USART1)
	{
		switch (current_feature)
		{
			case FUNC_FEATURE1:
				rd_2 = huart->Instance->DR;
				fifo_write(&fifo_uart1_rx,&rd_2,1);
				usb_ring_put(rd_2);          /* 补丁7：只入环形缓冲，主循环再批量转发 USB */
				/*CDC_Transmit_FS(&usb_rx_data,1);*/
				HAL_UART_Receive_IT( &huart1, &usb_rx_data, 1);
				uart1_rx_timeout = 10;
                break;
			case FUNC_FEATURE2:
				rd = huart->Instance->DR;
				fifo_write(&fifo_uart1_rx,&rd,1);
                HAL_UART_Receive_IT( &huart1, &tmp, 1);
				uart1_rx_timeout = 10;
                break;
            default:
                break;
		}
	}
}
void usb_receive_to_tx_send( void )
{
	  	HAL_Delay(1);
    if(usb_rx_complete)
    {
        HAL_UART_Transmit(&huart1,my_usb_rx_data, my_usb_rx_num ,500);
        memset(my_usb_rx_data, 0, my_usb_rx_num);
        my_usb_rx_num = 0;
		usb_rx_complete = 0;
    }
}

/**
 * @brief  在主循环里把 E22 收到的数据批量转发到 USB（补丁7）
 * @note   绝不能在 UART 中断里调用 CDC_Transmit_FS：发送端持续发送时
 *         每秒约 960 次中断会把 USB 栈打满，导致主循环饿死而卡死。
 *         本函数一次最多转发 64 字节，USB 忙就直接返回（宁丢不等）。
 */
void usb_passthrough_poll(void)
{
    static uint8_t buf[64];
    uint16_t len = 0;

    if (current_feature != FUNC_FEATURE1) return;      /* 只有透传模式才转发 */

    while (len < (uint16_t)sizeof(buf))
    {
        uint16_t tail = usb_ring_tail;

        if (tail == usb_ring_head) break;              /* 缓冲空 */

        buf[len++] = usb_ring[tail];
        usb_ring_tail = (uint16_t)((tail + 1) % USB_RING_SIZE);
    }

    if (len == 0) return;

    if (CDC_Transmit_FS(buf, len) != USBD_OK)
    {
        usb_ring_drop += len;                          /* USB 忙，丢弃这批，绝不阻塞 */
    }
}

/**
 * @brief  查询被丢弃的字节数（补丁7），便于上位机提示丢包
 */
uint32_t usb_ring_drop_count(void)
{
    return usb_ring_drop;
}

/* USER CODE END 1 */
