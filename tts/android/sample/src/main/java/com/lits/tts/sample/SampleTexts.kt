package com.lits.tts.sample

internal object SampleTexts {
    fun forLanguage(language: String): String {
        return if (language == "en-US") {
            "Welcome to the Lits delivery TTS sample. Room 204 is ready."
        } else {
            """
                那天午后，我去港口取一只修好的钟。店主说，零件还没有送到。我在柜台前站了一会儿，看见墙上挂着十几只钟，每一只都指向不同的时刻。他没有解释，我也没有问。门外的阳光落在台阶上，白得令人睁不开眼。

                The street was almost empty. A dog slept beneath a parked truck, its paws resting in a narrow strip of shade. Somewhere behind the houses, a woman was shaking out a sheet. For a moment, the white cloth rose above the wall and held the light.

                我沿着电车轨道往海边走。鞋底有一粒沙子，每走几步，它就挪动一下。我本来可以停下来把它倒掉，却一直没有停。街角的水果摊收了遮阳布，一个男孩正把滚到路上的橙子捡回木箱。他递给我一个，说这个已经碰坏了。我付了钱。他看着手里的硬币，似乎想说什么，最后只是把脸转向海风。

                I sat on a low wall and peeled the orange. The skin broke beneath my thumb, and a little juice ran down my wrist. A boat was leaving the harbour. I watched it until I could no longer tell whether it was moving or whether the afternoon itself was slowly carrying it away.

                昨天，姐姐来信，问我打算在这里住到什么时候。信纸上还有她擦去一个字留下的破口。我把信读了两遍，折好，放进抽屉。我不知道该给她一个日期，还是说说这间屋子的窗户。每天傍晚，窗框的影子都会爬过床边，停在一块裂开的地砖上。那块砖已经裂了很久，房东答应过要换。

                海水撞在堤岸上，声音很近。远处有人叫了一个名字，叫第二遍时，风把后半截吹散了。我吃完橙子，将果皮放在膝上。此刻没有人等我回去，钟表店也不会在今天关门以前收到零件。我还有很长的一段下午，需要自己过完。

                There was no answer waiting in the water. I stayed there anyway. The stone was warm beneath my hands, and the salt had dried on my sleeve. When the boat disappeared, I stood up. A small fishing line had caught around my shoe. I bent down and patiently worked it loose.

                回去的时候，水果摊已经空了。男孩坐在木箱上吃面包，脚够不着地。他认出了我，问橙子甜不甜。我说，很甜。他点点头，继续吃他的面包。我走过那条街，终于停在路边，脱下鞋，把里面的沙子倒了出来。
            """.trimIndent()
        }
    }
}
