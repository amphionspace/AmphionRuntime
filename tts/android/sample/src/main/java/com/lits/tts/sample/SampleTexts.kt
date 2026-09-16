package com.lits.tts.sample

internal object SampleTexts {
    fun forLanguage(language: String): String {
        return if (language == "en-US") {
            "Welcome to the Lits delivery TTS sample. Room 204 is ready."
        } else {
            """
                计算机视觉领域，历年顶会和业界征战数千余场，是非曲直
                难以论说，但研究者无不注意到，正是在各类赛道上，决定
                了多少代模型架构和范式的盛衰兴亡、此兴彼落，所以向来
                就有问鼎智能核心之说。
                当年AlexNet领革命军分三路会师ImageNet，兴师北上，拿
                下图像分类榜首的第二天，SIFT和HOG 等传统手工特征见
                大势已去，宣告无法成为主流。2018年之后，也正是在自
                监督赛场，恺明系列工作携数百万研究者征讨目标检测、实
                例分割、表征分类，斩获数篇最佳论文，大获全胜！
                我不明白，为什么大家都在谈论着 GPT-astra 横扫AI圈，
                仿佛这计算机视觉的未来注定了凶多吉少。十年前，我们从
                深度视觉赛道踏上征途，开始了通用感知浪潮，CV黄金版图
                遂归于一统。本领域所到之处，SOTA悉数刷新，真可谓占
                尽天时，那种勃勃生机、万物竞发的境界，犹在眼前。短短
                十年之后，这里竟至于一变而成为我们的葬身之地了么？
                无论怎么讲，会战兵力，是多模态生成、3D、多模态理解、
                具身智能，四大赛道对单一文本，优势在我！
            """.trimIndent()
        }
    }
}
