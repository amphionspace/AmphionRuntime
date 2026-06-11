package com.amphion.police.plate

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.BufferedReader
import java.io.StringReader

class PlateNormalizerTest {

    private lateinit var normalizer: PlateNormalizer

    @Before
    fun setUp() {
        val csv = """
            from,to,category
            经,京,province
            冀,冀,province
            继,冀,province
            济,冀,province
            记,冀,province
            即,冀,province
            纪,冀,province
            季,冀,province
            辽,辽,province
            币,B,letter
            毕,B,letter
            诶,A,letter
            零,0,digit
            幺,1,digit
            一,1,digit
            二,2,digit
            三,3,digit
            四,4,digit
            五,5,digit
            六,6,digit
            七,7,digit
            八,8,digit
            九,9,digit
            外,Y,letter
            优,U,letter
            义,E,letter
            替,T,letter
            浙,浙,province
            这,浙,province
            素,苏,province
            属,苏,province
            苏,苏,province
            皖,皖,province
            闽,闽,province
            晚,皖,province
            碗,皖,province
            万,皖,province
            挽,皖,province
            缅,闽,province
            干,赣,province
            赣,赣,province
            鲁,鲁,province
            豫,豫,province
            乳,鲁,province
            余,豫,province
            玉,豫,province
            碧,B,letter
            壁,B,letter
            笔,B,letter
            北,B,letter
            撂,辽,province
            翼,E,letter
            寺,4,digit
            批,P,letter
            衣,1,digit
            要,1,digit
            外,Y,letter
            恩,N,letter
            地,D,letter
            芸,云,province
            闪,陕,province
            账,藏,province
            轻,青,province
            清,青,province
            肝,甘,province
            感,甘,province
            杆,甘,province
            镇,J,letter
            奥,澳,province
            辟,P,letter
            开,K,letter
        """.trimIndent()
        val dict = PlateHomophoneDict.loadFromReader(BufferedReader(StringReader(csv)))
        normalizer = PlateNormalizer.create(dict)
    }

    @Test
    fun standardPlate_unchanged() {
        val r = normalizer.normalize("请核查车牌号冀R42388车辆信息")
        assertEquals("请核查车牌号冀R42388车辆信息", r.text)
        assertNotNull(r.primaryPlate)
        assertEquals("冀R42388", r.primaryPlate)
    }

    @Test
    fun homophoneAndChineseDigits_corrected() {
        val r = normalizer.normalize("拦截京诶一二三四五重复")
        assertTrue(r.spans.any { it.valid })
        assertEquals("京A12345", r.primaryPlate)
        assertEquals("拦截京A12345重复", r.text)
    }

    @Test
    fun newEnergyPlate_valid() {
        val r = normalizer.normalize("发现冀RFY7268涉嫌违章")
        assertEquals("冀RFY7268", r.primaryPlate)
    }

    @Test
    fun asrGrMisheard_correctedToJiR() {
        val r = normalizer.normalize("请核查车牌号GR零P幺九N车辆信息")
        assertEquals("冀R0P19N", r.primaryPlate)
        assertTrue(r.spans.any { it.valid })
    }

    @Test
    fun asrGSpaceRMisheard_correctedToJiR() {
        val r = normalizer.normalize("请核查车牌号G R幺零五七M车辆信息")
        assertEquals("冀R1057M", r.primaryPlate)
    }

    @Test
    fun asrJiErMisheard_correctedToJiR() {
        val r = normalizer.normalize("请核查车牌号，继而零四五四六车辆信息")
        assertEquals("冀R04546", r.primaryPlate)
    }

    @Test
    fun asrG二Misheard_correctedToJiR() {
        val r = normalizer.normalize("请核查车牌号G二零五六三外车辆信息")
        assertEquals("冀R0563Y", r.primaryPlate)
    }

    @Test
    fun asrJiEr28L81_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号济儿二八L八幺车辆信息")
        assertEquals("冀R28L81", r.primaryPlate)
    }

    @Test
    fun asrJiEr42388_withCommaAnchor() {
        val r = normalizer.normalize("请核查车牌号，继而四二三八八车辆信息")
        assertEquals("冀R42388", r.primaryPlate)
    }

    @Test
    fun asrJiEr42388_orphanFragment() {
        val r = normalizer.normalize("继而四二三八八车辆信息")
        assertEquals("冀R42388", r.primaryPlate)
    }

    @Test
    fun asrJiEr41489_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号记二四幺四八九车辆信息")
        assertEquals("冀R41489", r.primaryPlate)
    }

    @Test
    fun asrG二0563Y_withTrailingPeriod() {
        val r = normalizer.normalize("请核查车牌号G二零五六三外车辆信息。")
        assertEquals("冀R0563Y", r.primaryPlate)
    }

    @Test
    fun asrLiaoBi03062_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号辽币零三零六二车辆信息。")
        assertEquals("辽B03062", r.primaryPlate)
        assertTrue(r.spans.any { it.valid })
    }

    @Test
    fun asrLiaoBi05K2Y_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号辽毕零五K二Y车辆信息。")
        assertEquals("辽B05K2Y", r.primaryPlate)
        assertTrue(r.spans.any { it.valid })
    }

    @Test
    fun asrJiEr0P19N_jiErAndJiErVariants() {
        assertEquals(
            "冀R0P19N",
            normalizer.normalize("请核查车外号季儿零P幺九N车辆信息。").primaryPlate,
        )
        assertEquals(
            "冀R0P19N",
            normalizer.normalize("请核查车牌号纪儿零P幺九N车辆信息。").primaryPlate,
        )
    }

    @Test
    fun asrJiEr22046_doubleErAfterR() {
        val r = normalizer.normalize("请核查车牌号纪儿二二零四六车辆信息。")
        assertEquals("冀R22046", r.primaryPlate)
    }

    @Test
    fun asrJiEr22585_jiErErPattern() {
        val r = normalizer.normalize("请核查车牌号记二二五八五车辆信息。")
        assertEquals("冀R22585", r.primaryPlate)
    }

    @Test
    fun asrGr278B7_collapseExtraTwo() {
        assertEquals(
            "冀R278B7",
            normalizer.normalize("请核查出牌号GR二二七八B七车辆信息。").primaryPlate,
        )
        assertEquals(
            "冀R278B7",
            normalizer.normalize("请核查车牌号GR二二七八B七车辆信息。").primaryPlate,
        )
    }

    @Test
    fun asrGr28L81_collapseExtraTwo() {
        val r = normalizer.normalize("请核查车牌号GR二二八L八幺车辆信息。")
        assertEquals("冀R28L81", r.primaryPlate)
    }

    @Test
    fun asrLiaoB098D5_diWuMisheardAsD5() {
        val r = normalizer.normalize("请核查车牌号辽B零九八第五车辆信息。")
        assertEquals("辽B098D5", r.primaryPlate)
        assertTrue(r.spans.any { it.valid })
    }

    @Test
    fun asrJiG_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号G G七N四八H车辆信息。")
        assertEquals("冀G7N48H", r.primaryPlate)
    }

    @Test
    fun asrJiH_jiH_fromUserEval() {
        val r = normalizer.normalize("拦截记H三零五六四重复请前方布控。")
        assertEquals("冀H30564", r.primaryPlate)
    }

    @Test
    fun asrJiR_atCheZhuAnchor_fromUserEval() {
        val r = normalizer.normalize("即二四二三八八车主请配合检查。")
        assertEquals("冀R42388", r.primaryPlate)
    }

    @Test
    fun asrJinA_fromUserEval() {
        val r = normalizer.normalize("追踪目标进A二六九幺六，最后出现在哪？")
        assertEquals("晋A26916", r.primaryPlate)
    }

    @Test
    fun asrMengA_mengFromUserEval() {
        val r = normalizer.normalize("猛A七零幺B六，请靠边停车接受检。")
        assertEquals("蒙A701B6", r.primaryPlate)
    }

    @Test
    fun asrMengB_mengBiFromUserEval() {
        val r = normalizer.normalize("和对蒙蔽三三三八七是否与报案车辆一致？")
        assertEquals("蒙B33387", r.primaryPlate)
    }

    @Test
    fun asrLiaoE_liaoE_fromUserEval() {
        val r = normalizer.normalize("发现疗E幺八二四四涉嫌违章请确认。")
        assertEquals("辽E18244", r.primaryPlate)
    }

    @Test
    fun asrLiaoFC_fromUserEval() {
        val r = normalizer.normalize("聊FC六四零零车主请配个检查。")
        assertEquals("辽FC6400", r.primaryPlate)
    }

    @Test
    fun asrLiaoDX_liaoDi_fromUserEval() {
        val r = normalizer.normalize("拦截辽地X八四幺一重重复。")
        assertEquals("辽DX8411", r.primaryPlate)
    }

    @Test
    fun round4_liaoL_liuL_fromUserEval() {
        val r = normalizer.normalize("六LF五六三四已纳入布控名单。")
        assertEquals("辽LF5634", r.primaryPlate)
    }

    @Test
    fun round4_liaoMB_anBi_fromUserEval() {
        val r = normalizer.normalize("查询辽安比七三G七近七日通行记录。")
        assertEquals("辽MB73G7", r.primaryPlate)
    }

    @Test
    fun round4_liaoN_liaoEn_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号，聊恩三A三六五车辆信息。")
        assertEquals("辽N3A365", r.primaryPlate)
    }

    @Test
    fun round4_jiA_jiA_fromUserEval() {
        val r = normalizer.normalize("发现即A幺四二九四涉嫌违章请确认。")
        assertEquals("吉A14294", r.primaryPlate)
    }

    @Test
    fun round4_jiB_atCheZhu_fromUserEval() {
        val r = normalizer.normalize("即B九六五五六车主请配合检查。")
        assertEquals("吉B96556", r.primaryPlate)
    }

    @Test
    fun round4_jiG_jiZhiYi_fromUserEval() {
        val r = normalizer.normalize("即制以七三八R二已纳入布控车辆。")
        assertEquals("吉G738R2", r.primaryPlate)
    }

    @Test
    fun round4_heiB_heiBi_fromUserEval() {
        val r = normalizer.normalize("黑碧八七零八三，车主请配合检查。")
        assertEquals("黑B87083", r.primaryPlate)
    }

    @Test
    fun round4_heiE_heiYi_fromUserEval() {
        val r = normalizer.normalize("黑翼三四S七三，请靠边停车接受检。")
        assertEquals("黑E34S73", r.primaryPlate)
    }

    @Test
    fun round5_heiM_heiAnMu_fromUserEval() {
        val r = normalizer.normalize("发现黑暗慕四六七零六涉嫌违章请确认。")
        assertEquals("黑M46706", r.primaryPlate)
    }

    @Test
    fun round5_heiN_heiEn_fromUserEval() {
        val r = normalizer.normalize("黑恩七义九替零车主请配合检查。")
        assertEquals("黑N7E9T0", r.primaryPlate)
    }

    @Test
    fun round5_suB_suBiYao_fromUserEval() {
        val r = normalizer.normalize("和对苏必要W零零三是否与报案车辆一致？")
        assertEquals("苏B1W003", r.primaryPlate)
    }

    @Test
    fun round5_suD_suDi_fromUserEval() {
        val r = normalizer.normalize("查询苏堤四M二V九，近七日通行记录。")
        assertEquals("苏D4M2V9", r.primaryPlate)
    }

    @Test
    fun round5_suG_shuJi_fromUserEval() {
        val r = normalizer.normalize("发现书记T六X五幺涉嫌违章请确。")
        assertEquals("苏GT6X51", r.primaryPlate)
    }

    @Test
    fun round5_suH_suSu_fromUserEval() {
        val r = normalizer.normalize("素H六七幺六五车主请配合检查。")
        assertEquals("苏H67165", r.primaryPlate)
    }

    @Test
    fun round5_zheA_zheFromUserEval() {
        val r = normalizer.normalize("查询这A六七八三七近七日通行记录。")
        assertEquals("浙A67837", r.primaryPlate)
    }

    @Test
    fun round5_zheD_zheDi_fromUserEval() {
        val r = normalizer.normalize("发现这第四四H幺涉嫌违章请确认。")
        assertEquals("浙D444H1", r.primaryPlate)
    }

    @Test
    fun round5_zheEZ_zheYiZ_fromUserEval() {
        val r = normalizer.normalize("这一Z八二三三车主请配合检查。")
        assertEquals("浙EZ8233", r.primaryPlate)
    }

    @Test
    fun round7_wanA_wanFromUserEval() {
        val r = normalizer.normalize("请核查车牌号晚A三幺八六九车辆信息。")
        assertEquals("皖A31869", r.primaryPlate)
    }

    @Test
    fun round7_wanB_wanBiFromUserEval() {
        val r = normalizer.normalize("拦截碗壁九六K九九，重复请前方布控。")
        assertEquals("皖B96K99", r.primaryPlate)
    }

    @Test
    fun round7_wanD_wanDi_fromUserEval() {
        val r = normalizer.normalize("晚地七四零三K车主请配合检查。")
        assertEquals("皖D7403K", r.primaryPlate)
    }

    @Test
    fun round7_wanE_wangYi_fromUserEval() {
        val r = normalizer.normalize("通报网易X三四W九为重点关注车辆。")
        assertEquals("皖EX34W9", r.primaryPlate)
    }

    @Test
    fun round7_wanN_wanEn_fromUserEval() {
        val r = normalizer.normalize("发现晚恩五六七四六涉嫌违章请确认。")
        assertEquals("皖N56746", r.primaryPlate)
    }

    @Test
    fun round7_wanK_wanKe_fromUserEval() {
        val r = normalizer.normalize("查询万科幺三九九零近七日通行记录。")
        assertEquals("皖K13990", r.primaryPlate)
    }

    @Test
    fun round7_minB_minBi_fromUserEval() {
        val r = normalizer.normalize("和对闽碧C三幺Q幺是否与报案车辆一致？")
        assertEquals("闽BC31Q1", r.primaryPlate)
    }

    @Test
    fun round7_minC_mianShui_fromUserEval() {
        val r = normalizer.normalize("免税八四P七七已纳入不可名单。")
        assertEquals("闽C84P77", r.primaryPlate)
    }

    @Test
    fun round7_minD_mianDi_fromUserEval() {
        val r = normalizer.normalize("查询缅地二六三九S近七日通行记录。")
        assertEquals("闽D2639S", r.primaryPlate)
    }

    @Test
    fun round8_minF_mianJiu_fromUserEval() {
        val r = normalizer.normalize("拦截免九九X七二重复请前方布控。")
        assertEquals("闽F99X72", r.primaryPlate)
    }

    @Test
    fun round8_minJ_minZhen_fromUserEval() {
        val r = normalizer.normalize("通报闽镇七币二八九为重点关注车辆。")
        assertEquals("闽J7B289", r.primaryPlate)
    }

    @Test
    fun round8_minK_minKai_fromUserEval() {
        val r = normalizer.normalize("追踪目标，闽凯七幺八七零最后出现。")
        assertEquals("闽K71870", r.primaryPlate)
    }

    @Test
    fun round8_ganH_ganFromUserEval() {
        val r = normalizer.normalize("干H八二C七五车主请配合检查。")
        assertEquals("赣H82C75", r.primaryPlate)
    }

    @Test
    fun round8_ganCD_ganXiDi_fromUserEval() {
        val r = normalizer.normalize("赣西地幺七F四已纳入布控名单。")
        assertEquals("赣CD17F4", r.primaryPlate)
    }

    @Test
    fun round8_ganE_ganYi_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号，赣翼三八六九二车辆信息。")
        assertEquals("赣E38692", r.primaryPlate)
    }

    @Test
    fun round8_ganF_ganFromUserEval() {
        val r = normalizer.normalize("拦截干F幺九六九三，重复请前方布控。")
        assertEquals("赣F19693", r.primaryPlate)
    }

    @Test
    fun round8_ganLK_ganFromUserEval() {
        val r = normalizer.normalize("干LK三九M三，请靠边停车接受检查。")
        assertEquals("赣LK39M3", r.primaryPlate)
    }

    @Test
    fun round8_luC_luXi_fromUserEval() {
        val r = normalizer.normalize("查询鲁西二四R四Z近七日通行记录。")
        assertEquals("鲁C24R4Z", r.primaryPlate)
    }

    @Test
    fun round9_luD_luDi_fromUserEval() {
        val r = normalizer.normalize("经核查，车牌号鲁地七幺二三六车辆信息。")
        assertEquals("鲁D71236", r.primaryPlate)
    }

    @Test
    fun round9_luE_luYi_fromUserEval() {
        val r = normalizer.normalize("拦截鲁翼六零四八幺重复请前方布控。")
        assertEquals("鲁E60481", r.primaryPlate)
    }

    @Test
    fun round9_luY_ruWai_fromUserEval() {
        val r = normalizer.normalize("发现乳外九六W五幺涉嫌违章请确认。")
        assertEquals("鲁Y96W51", r.primaryPlate)
    }

    @Test
    fun round9_luP_luPin_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号鲁聘三L二九A车辆信息。")
        assertEquals("鲁P3L29A", r.primaryPlate)
    }

    @Test
    fun round9_luR_luEr_fromUserEval() {
        val r = normalizer.normalize("发现鲁二零五三九五涉嫌违章请确认。")
        assertEquals("鲁R05395", r.primaryPlate)
    }

    @Test
    fun round9_yuA_yuFromUserEval() {
        val r = normalizer.normalize("余A四零二六八车主请配合检查。")
        assertEquals("豫A40268", r.primaryPlate)
    }

    @Test
    fun round9_yuB_yuBei_fromUserEval() {
        val r = normalizer.normalize("通报预备Q五八优衣为重点关注车辆。")
        assertEquals("豫BQ58U1", r.primaryPlate)
    }

    @Test
    fun round9_yuE_yuYi_fromUserEval() {
        val r = normalizer.normalize("和对玉翼二四九九八是否已报案，车辆一致？")
        assertEquals("豫E24998", r.primaryPlate)
    }

    @Test
    fun round9_yuF_yuFromUserEval() {
        val r = normalizer.normalize("与F八四七八V已纳入布控名单。")
        assertEquals("豫F8478V", r.primaryPlate)
    }

    @Test
    fun round9_yuG_yuJi_fromUserEval() {
        val r = normalizer.normalize("查询预计幺八三六七近七日通行记录。")
        assertEquals("豫G18367", r.primaryPlate)
    }

    @Test
    fun round11_kespeech_grToJiR() {
        val r = normalizer.normalize("麻烦帮我核查GR八三三八零车辆情况。")
        assertEquals("冀R83380", r.primaryPlate)
    }

    @Test
    fun round11_kespeech_gErToJiR() {
        val r = normalizer.normalize("帮忙核查一下车牌号为G二六五四三八的情况。")
        assertEquals("冀R65438", r.primaryPlate)
    }

    @Test
    fun round11_kespeech_weiJiEr() {
        val r = normalizer.normalize("帮忙核查一下车牌号违纪而六五四三八的情况。")
        assertEquals("冀R65438", r.primaryPlate)
    }

    @Test
    fun round11_kespeech_plateJiEr() {
        val r = normalizer.normalize("帮忙核查车牌号及二九四三九零的车辆基础信息。")
        assertEquals("冀R94390", r.primaryPlate)
    }

    @Test
    fun round11_kespeech_jiR_notJiLin() {
        val r = normalizer.normalize("麻烦看一下车牌号，即R三五四零二车辆信息。")
        assertEquals("冀R35402", r.primaryPlate)
    }

    @Test
    fun round11_kespeech_liaoB_thisVehicle() {
        val r = normalizer.normalize("麻烦核实一下辽B六五四三八这辆车的情况。")
        assertEquals("辽B65438", r.primaryPlate)
    }

    @Test
    fun round11_kespeech_liaoBi_plateWei() {
        val r = normalizer.normalize("帮忙确认一下车牌号为辽笔四零三八二的车辆状态。")
        assertEquals("辽B40382", r.primaryPlate)
    }

    @Test
    fun round11_kespeech_liaoBei() {
        val r = normalizer.normalize("帮忙查一下辽北三幺五幺七对应车辆的情况。")
        assertEquals("辽B31517", r.primaryPlate)
    }

    @Test
    fun round11_kespeech_liaoTalkB() {
        val r = normalizer.normalize("帮忙看一下车牌号，聊B六七九零八有没有相关记录？")
        assertEquals("辽B67908", r.primaryPlate)
    }

    @Test
    fun round11_kespeech_jiEr_double() {
        val r = normalizer.normalize("麻烦核实一下，即二二六七二四这辆车的情况。")
        assertEquals("冀R26724", r.primaryPlate)
    }

    @Test
    fun round12_manual_jiErComma() {
        val r = normalizer.normalize("看一下车牌号为继，而九八六七零的车辆有没有处置记？")
        assertEquals("冀R98670", r.primaryPlate)
    }

    @Test
    fun round12_manual_gEr() {
        val r = normalizer.normalize("看一下车牌号为G而九八六七零的车辆有没有处置记录？")
        assertEquals("冀R98670", r.primaryPlate)
    }

    // round15 豫/鄂/湘 手测（plate_eval_one_per_plate 161–190）
    @Test
    fun round15_yuH_yuWith_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号与H七六P幺五车辆信息。")
        assertEquals("豫H76P15", r.primaryPlate)
    }

    @Test
    fun round15_yuK_yuJade_fromUserEval() {
        val r = normalizer.normalize("发现玉K幺六幺五二涉嫌违章请确认。")
        assertEquals("豫K16152", r.primaryPlate)
    }

    @Test
    fun round15_yuL_yuWith_fromUserEval() {
        val r = normalizer.normalize("与L幺六M六Z车主请配合检查。")
        assertEquals("豫L16M6Z", r.primaryPlate)
    }

    @Test
    fun round15_yuM_yuMeet_fromUserEval() {
        val r = normalizer.normalize("通报遇M四五幺九S为重点关注车辆。")
        assertEquals("豫M4519S", r.primaryPlate)
    }

    @Test
    fun round15_yuN_yuEn_fromUserEval() {
        val r = normalizer.normalize("追踪目标，玉恩七三幺五八，最后出现在。")
        assertEquals("豫N73158", r.primaryPlate)
    }

    @Test
    fun round15_yuP_yuBi_fromUserEval() {
        val r = normalizer.normalize("御辟四九三六八，请靠边停车接受检查。")
        assertEquals("豫P49368", r.primaryPlate)
    }

    @Test
    fun round15_yuQ_yuPre_fromUserEval() {
        val r = normalizer.normalize("和对预QF四Y四五是否与报案车辆一致？")
        assertEquals("豫QF4Y45", r.primaryPlate)
    }

    @Test
    fun round15_yuSz_yuWith_fromUserEval() {
        val r = normalizer.normalize("查询与SZ八三六P近七日通行记录。")
        assertEquals("豫SZ836P", r.primaryPlate)
    }

    @Test
    fun round15_yuU_yuMeet_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号遇U五K五九九车辆信息。")
        assertEquals("豫U5K599", r.primaryPlate)
    }

    @Test
    fun round15_eG_eNotJiR_fromUserEval() {
        val r = normalizer.normalize("俄G二二六T三请靠边停车接受检查。")
        assertEquals("鄂G226T3", r.primaryPlate)
    }

    @Test
    fun round15_eE_eMalice_fromUserEval() {
        val r = normalizer.normalize("通报恶意三六九零零为重点关注车辆。")
        assertEquals("鄂E36900", r.primaryPlate)
    }

    @Test
    fun round15_eJ_eZhui_fromUserEval() {
        val r = normalizer.normalize("俄坠六九六六K已纳入布控名单。")
        assertEquals("鄂J6966K", r.primaryPlate)
    }

    @Test
    fun round15_eM_eRussian_fromUserEval() {
        val r = normalizer.normalize("拦截俄M五三L二一重复请前方布控。")
        assertEquals("鄂M53L21", r.primaryPlate)
    }

    @Test
    fun round15_eS_eGoose_fromUserEval() {
        val r = normalizer.normalize("发现鹅S五M二三D涉嫌违章请确。")
        assertEquals("鄂S5M23D", r.primaryPlate)
    }

    @Test
    fun round15_eCp_eXiPi_fromUserEval() {
        val r = normalizer.normalize("厄斯皮要K九七车主请配合检查。")
        assertEquals("鄂CP1K97", r.primaryPlate)
    }

    @Test
    fun round15_eN_eEn_fromUserEval() {
        val r = normalizer.normalize("追踪目标，厄恩七幺七七四最后出现。")
        assertEquals("鄂N71774", r.primaryPlate)
    }

    @Test
    fun round15_eRs_eErS_fromUserEval() {
        // ASR 将「幺五」连读为 15，与真值 1 不符，当前规则不强行修
        val r = normalizer.normalize("厄尔S幺五K七七靠遍停车接受检查。")
        assertEquals(null, r.primaryPlate)
    }

    @Test
    fun round15_eP_ePi_fromUserEval() {
        val r = normalizer.normalize("和对恶皮五四幺幺九是否与报案车辆一致？")
        assertEquals("鄂P54119", r.primaryPlate)
    }

    @Test
    fun round15_xiangA_xiangFromUserEval() {
        val r = normalizer.normalize("向A八零七九W已纳入布控零。")
        assertEquals("湘A8079W", r.primaryPlate)
    }

    @Test
    fun round15_xiangB_xiangBi_fromUserEval() {
        val r = normalizer.normalize("查询相比七八二零Q近期日通行记录。")
        assertEquals("湘B7820Q", r.primaryPlate)
    }

    // round16 湘/粤 手测（plate_eval_one_per_plate 191–225）
    @Test
    fun round16_xiangD_xiangDi_fromUserEval() {
        val r = normalizer.normalize("拦截乡第五M四六P重复请前方布控。")
        assertEquals("湘D5M46P", r.primaryPlate)
    }

    @Test
    fun round16_xiangE_xiangXiang_fromUserEval() {
        val r = normalizer.normalize("发现香E W五幺五D涉嫌违章请确认。")
        assertEquals("湘EW515D", r.primaryPlate)
    }

    @Test
    fun round16_xiangF_xiangLike_fromUserEval() {
        val r = normalizer.normalize("像F九二L幺九车主请配合检查。")
        assertEquals("湘F92L19", r.primaryPlate)
    }

    @Test
    fun round16_xiangL_xiangXiang_fromUserEval() {
        val r = normalizer.normalize("和对香L幺四幺八八是否与报案车辆一致？")
        assertEquals("湘L14188", r.primaryPlate)
    }

    @Test
    fun round16_xiangN_xiangEn_fromUserEval() {
        val r = normalizer.normalize("查询相恩三七V四七近七日通行记录。")
        assertEquals("湘N37V47", r.primaryPlate)
    }

    @Test
    fun round16_xiangK_xiangXiang_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号相K五X九七七车辆信息。")
        assertEquals("湘K5X977", r.primaryPlate)
    }

    @Test
    fun round16_xiangU_xiangYou_fromUserEval() {
        val r = normalizer.normalize("拦截相优八六二三V重复请前方布控。")
        assertEquals("湘U8623V", r.primaryPlate)
    }

    @Test
    fun round16_yueA_yueHappy_fromUserEval() {
        val r = normalizer.normalize("发现悦AW七五八幺涉嫌违章请确认。")
        assertEquals("粤AW7581", r.primaryPlate)
    }

    @Test
    fun round16_yueB_yueMoon_fromUserEval() {
        val r = normalizer.normalize("月BF四七八二车主请配合检查。")
        assertEquals("粤BF4782", r.primaryPlate)
    }

    @Test
    fun round16_yueC_yueXi_fromUserEval() {
        val r = normalizer.normalize("通报岳西三七五零六为重点关注车。")
        assertEquals("粤C37506", r.primaryPlate)
    }

    @Test
    fun round16_yueD_yueDi_fromUserEval() {
        val r = normalizer.normalize("追踪目标越第五三六幺M最后出现在。")
        assertEquals("粤D5361M", r.primaryPlate)
    }

    @Test
    fun round16_yueE_yueYi_fromUserEval() {
        val r = normalizer.normalize("岳翼五幺五二二，请靠边停车接受检查。")
        assertEquals("粤E51522", r.primaryPlate)
    }

    @Test
    fun round16_yueF_yueMoon_fromUserEval() {
        val r = normalizer.normalize("和对月F二七七V零是否与抱怨车辆一致？")
        assertEquals("粤F277V0", r.primaryPlate)
    }

    @Test
    fun round16_yueG_yueJi_fromUserEval() {
        val r = normalizer.normalize("月季四三二八九已纳入布控名单。")
        assertEquals("粤G43289", r.primaryPlate)
    }

    @Test
    fun round16_yueH_yueMoon_fromUserEval() {
        val r = normalizer.normalize("查询月H四三四幺零近七日通行记录。")
        assertEquals("粤H43410", r.primaryPlate)
    }

    @Test
    fun round16_yueK_yueYue_fromUserEval() {
        val r = normalizer.normalize("拦截岳K二K六零V重复请前方布控。")
        assertEquals("粤K2K60V", r.primaryPlate)
    }

    @Test
    fun round16_yueM_yueAnMo_fromUserEval() {
        // ASR 仅三个「八」，凑不出 M88888
        val r = normalizer.normalize("岳按摩八八八车主请配合检查。")
        assertEquals(null, r.primaryPlate)
    }

    @Test
    fun round16_yueN_yueEn_fromUserEval() {
        // 前缀岳恩→粤N 正确；末位 ASR 读成 G 非 J
        val r = normalizer.normalize("通报岳恩零六五G零为重点关注车辆。")
        assertEquals("粤N065G0", r.primaryPlate)
    }

    @Test
    fun round16_yueP_yueYue_fromUserEval() {
        val r = normalizer.normalize("追踪目标越P五三幺九五，最后出现在。")
        assertEquals("粤P53195", r.primaryPlate)
    }

    @Test
    fun round16_yueQ_yueMoon_fromUserEval() {
        val r = normalizer.normalize("月Q五八五二七，请靠边停车接受检。")
        assertEquals("粤Q58527", r.primaryPlate)
    }

    @Test
    fun round16_yueS_yueYuan_fromUserEval() {
        val r = normalizer.normalize("原S三零五四八已纳入布控名单。")
        assertEquals("粤S30548", r.primaryPlate)
    }

    @Test
    fun round16_yueT_yueYue_fromUserEval() {
        val r = normalizer.normalize("查询岳T三四五零五近七日通行记录。")
        assertEquals("粤T34505", r.primaryPlate)
    }

    @Test
    fun round16_yueU_yueYou_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号月优五六六七六车辆信息。")
        assertEquals("粤U56676", r.primaryPlate)
    }

    @Test
    fun round16_yueV_yueYue_fromUserEval() {
        val r = normalizer.normalize("拦截岳V七七五八四重复请前方布控。")
        assertEquals("粤V77584", r.primaryPlate)
    }

    @Test
    fun round16_yueW_yueHappy_fromUserEval() {
        val r = normalizer.normalize("发现悦WP九二T四涉嫌违章请确认。")
        assertEquals("粤WP92T4", r.primaryPlate)
    }

    @Test
    fun round16_yueX_yuNotYu_fromUserEval() {
        val r = normalizer.normalize("与X幺五四四七车主请配合检查。")
        assertEquals("粤X15447", r.primaryPlate)
    }

    @Test
    fun round16_yuF_stillHenan_fromUserEval() {
        val r = normalizer.normalize("与F八四七八V已纳入布控名单。")
        assertEquals("豫F8478V", r.primaryPlate)
    }

    // round17 琼/川 手测（plate_eval_one_per_plate 239–262）
    @Test
    fun round17_qiongC_qiongXi_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号琼西八G二四九车辆信息。")
        assertEquals("琼C8J249", r.primaryPlate)
    }

    @Test
    fun round17_qiongE_qiongPoor_fromUserEval() {
        val r = normalizer.normalize("发现穷E幺零九四三涉嫌违章请确。")
        assertEquals("琼E10943", r.primaryPlate)
    }

    @Test
    fun round17_chuanG_chuanWear_fromUserEval() {
        val r = normalizer.normalize("穿GW八四W四车主请配合检查。")
        assertEquals("川GW84W4", r.primaryPlate)
    }

    @Test
    fun round17_chuanC_chuanXi_fromUserEval() {
        val r = normalizer.normalize("追踪目标穿西七七三L九，最后出现。")
        assertEquals("川C773L9", r.primaryPlate)
    }

    @Test
    fun round17_chuanD_chuanDi_fromUserEval() {
        val r = normalizer.normalize("传递五六E五八，请靠边停车接受检查。")
        assertEquals("川D56E58", r.primaryPlate)
    }

    @Test
    fun round17_chuanE_chuanYi_fromUserEval() {
        val r = normalizer.normalize("和对穿翼栖地四七三是否有报案，车辆一致？")
        assertEquals("川E7D473", r.primaryPlate)
    }

    @Test
    fun round17_chuanF_chuanWear_fromUserEval() {
        val r = normalizer.normalize("穿F零四六九六已纳入布控名单。")
        assertEquals("川F04696", r.primaryPlate)
    }

    @Test
    fun round17_chuanH_chuanWear_fromUserEval() {
        val r = normalizer.normalize("查询穿H五九五三二，近期日通行记录。")
        assertEquals("川H59532", r.primaryPlate)
    }

    @Test
    fun round17_chuanLp_chuanWear_fromUserEval() {
        val r = normalizer.normalize("发现穿LP二四五N涉嫌违章请确认。")
        assertEquals("川LP245N", r.primaryPlate)
    }

    @Test
    fun round17_chuanM_chuanWear_fromUserEval() {
        val r = normalizer.normalize("穿M六零九八三，车主请配合检查。")
        assertEquals("川M60983", r.primaryPlate)
    }

    @Test
    fun round17_chuanQn_chuanWear_fromUserEval() {
        val r = normalizer.normalize("通报穿QN八Q八四为重点关注车。")
        assertEquals("川QN8Q84", r.primaryPlate)
    }

    @Test
    fun round17_chuanR_chuanWear_fromUserEval() {
        // ASR 多一个「五」，凑不出 R16558
        val r = normalizer.normalize("追踪目标穿R二幺六五五八，最后出现在。")
        assertEquals(null, r.primaryPlate)
    }

    @Test
    fun round17_chuanS_chuanWear_fromUserEval() {
        val r = normalizer.normalize("穿S三九八六八，请靠边停车接受检查。")
        assertEquals("川S39868", r.primaryPlate)
    }

    @Test
    fun round17_chuanT_chuanDi_fromUserEval() {
        val r = normalizer.normalize("和对传递零二五七八是否与报案车辆一致？")
        assertEquals("川T02578", r.primaryPlate)
    }

    @Test
    fun round17_chuanV_chuanSpring_fromUserEval() {
        val r = normalizer.normalize("查询春V六九四九五，近七日通行记录。")
        assertEquals("川V69495", r.primaryPlate)
    }

    @Test
    fun round17_chuanW_chuanWear_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号穿W七零M五X车辆信息。")
        assertEquals("川W70M5X", r.primaryPlate)
    }

    @Test
    fun round17_chuanZ_asrLetter_fromUserEval() {
        // ASR 末位 G 非 J
        val r = normalizer.normalize("拦截川Z四零九七G重复请前款布控。")
        assertEquals("川Z4097G", r.primaryPlate)
    }

    // round18 云/藏/陕 手测（plate_eval_one_per_plate 272–306）
    @Test
    fun round18_yunA_fromUserEval() {
        val r = normalizer.normalize("拦截云A九九三三零重复请前方布控。")
        assertEquals("云A99330", r.primaryPlate)
    }

    @Test
    fun round18_yunC_asrMissingDigit_fromUserEval() {
        // ASR「六七幺二」仅 4 位，凑不出 65712
        val r = normalizer.normalize("发现云西六七幺二涉嫌违章请确。")
        assertEquals(null, r.primaryPlate)
    }

    @Test
    fun round18_yunG_yunJi_fromUserEval() {
        val r = normalizer.normalize("云计A四U九幺请靠边停车接受检查。")
        assertEquals("云GA4U91", r.primaryPlate)
    }

    @Test
    fun round18_yunH_asrE8_fromUserEval() {
        // ASR「一八」非 E8
        val r = normalizer.normalize("和对芸H八八七一八是否有报案车辆一致？")
        assertEquals("云H88718", r.primaryPlate)
    }

    @Test
    fun round18_yunJ_asrGarbled_fromUserEval() {
        // 前缀云坠→云J 正确，但 ASR「幺幺二七四」非 1L274
        val r = normalizer.normalize("云坠幺幺二七四已纳入布控名单。")
        assertEquals("云J11274", r.primaryPlate)
    }

    @Test
    fun round18_yunN_yunEnSi_fromUserEval() {
        val r = normalizer.normalize("发现云恩寺九Z九零涉嫌违章请确认。")
        assertEquals("云N49Z90", r.primaryPlate)
    }

    @Test
    fun round18_zangB_zangBi_fromUserEval() {
        val r = normalizer.normalize("藏币二L八七地已纳入不公名单。")
        assertEquals("藏B2L87D", r.primaryPlate)
    }

    @Test
    fun round18_zangC_zhang_fromUserEval() {
        val r = normalizer.normalize("查询账C八七零七二，近七日通行记录。")
        assertEquals("藏C87072", r.primaryPlate)
    }

    @Test
    fun round18_zangD_zangDi_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号藏地零八七四Z车辆信息。")
        assertEquals("藏D0874Z", r.primaryPlate)
    }

    @Test
    fun round18_zangE_asrGarbled_fromUserEval() {
        val r = normalizer.normalize("拦截藏一零三幺零，重复请前方布控。")
        assertEquals(null, r.primaryPlate)
    }

    @Test
    fun round18_shanA_shan_fromUserEval() {
        val r = normalizer.normalize("追踪目标闪A八六八二三，最后出现在。")
        assertEquals("陕A86823", r.primaryPlate)
    }

    @Test
    fun round18_shanG_shanG_noJiR_fromUserEval() {
        val r = normalizer.normalize("拦截闪G二八四三九，重复请前方布控。")
        assertEquals("陕G28439", r.primaryPlate)
    }

    @Test
    fun round18_shanDx_shanDiX_fromUserEval() {
        val r = normalizer.normalize("山迪X六九零H已纳入不空名单。")
        assertEquals("陕DX690H", r.primaryPlate)
    }

    @Test
    fun round18_shanE_shanYi_fromUserEval() {
        val r = normalizer.normalize("查询陕翼幺九零七九近七日通行记录。")
        assertEquals("陕E19079", r.primaryPlate)
    }

    @Test
    fun round18_shanJ_asrGarbled_fromUserEval() {
        // 山寨→陕J 正确，但 ASR「零八幺二六」非 08U26
        val r = normalizer.normalize("山寨零八幺二六车主请配合检查。")
        assertEquals("陕J08126", r.primaryPlate)
    }

    @Test
    fun round18_shanV_shanYu_fromUserEval() {
        val r = normalizer.normalize("这种目标善于四六二八七，最后出现在。")
        assertEquals("陕V46287", r.primaryPlate)
    }

    @Test
    fun round18_yunD_asrGarbled_fromUserEval() {
        // ASR 第七二二三K五 凑不出 D7R3K5
        val r = normalizer.normalize("云第七二二三K五车主请配合检查。")
        assertEquals(null, r.primaryPlate)
    }

    @Test
    fun round18_yunR_extraDigits_fromUserEval() {
        val r = normalizer.normalize("追踪目标云R二七九五六八，最后出现。")
        assertEquals(null, r.primaryPlate)
    }

    // round19 甘/青/宁 手测（plate_eval_one_per_plate 307–332）
    @Test
    fun round19_ganA_ganEn_fromUserEval() {
        val r = normalizer.normalize("感恩四二七零八，仅靠边停车接受检查。")
        assertEquals("甘A42708", r.primaryPlate)
    }

    @Test
    fun round19_ganC_ganC_notJiangxi_fromUserEval() {
        val r = normalizer.normalize("干C Q五幺八三人纳入布控名单。")
        assertEquals("甘CQ5183", r.primaryPlate)
    }

    @Test
    fun round19_ganD_ganDi_fromUserEval() {
        val r = normalizer.normalize("查询甘地九九零C三近七日通行记录。")
        assertEquals("甘D990C3", r.primaryPlate)
    }

    @Test
    fun round19_ganE_ganYi_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号干翼五K零三三车辆信息。")
        assertEquals("甘E5K033", r.primaryPlate)
    }

    @Test
    fun round19_ganF_ganAi_fromUserEval() {
        val r = normalizer.normalize("拦截甘F九Y三N三，重复请前方布控。")
        assertEquals("甘F9Y3N3", r.primaryPlate)
    }

    @Test
    fun round19_ganF_ganAi_asr_fromUserEval() {
        // ASR「外三三」非 Y3N3，仅能到甘F9Y33 且位数不足
        val r = normalizer.normalize("拦截肝癌负九外三三，重复请前方布控。")
        assertEquals(null, r.primaryPlate)
    }

    @Test
    fun round19_ganG_ganGan_fromUserEval() {
        val r = normalizer.normalize("发现肝G七八五K四涉嫌违章请确认。")
        assertEquals("甘G785K4", r.primaryPlate)
    }

    @Test
    fun round19_ganH_ganGan_fromUserEval() {
        val r = normalizer.normalize("感H七五三五五车主请配合检查。")
        assertEquals("甘H75355", r.primaryPlate)
    }

    @Test
    fun round19_ganJ_ganZhen_fromUserEval() {
        val r = normalizer.normalize("通报甘镇九三二零四维重点关注车。")
        assertEquals("甘J93204", r.primaryPlate)
    }

    @Test
    fun round19_ganK_ganGan_fromUserEval() {
        val r = normalizer.normalize("追踪目标杆K三L三六九最后出现在。")
        assertEquals("甘K3L369", r.primaryPlate)
    }

    @Test
    fun round19_ganL_ganGan_fromUserEval() {
        // ASR 多一个「零」→ 甘L54770Q 超长无效
        val r = normalizer.normalize("肝L五四七七零Q，请靠边停车接受检查。")
        assertEquals(null, r.primaryPlate)
    }

    @Test
    fun round19_ganM_ganAi_fromUserEval() {
        val r = normalizer.normalize("和对肝癌M八七二八零是否与保险车辆一致？")
        assertEquals("甘M87280", r.primaryPlate)
    }

    @Test
    fun round19_ganN_ganEn_fromUserEval() {
        val r = normalizer.normalize("感恩零零六二三已纳入补库名单。")
        assertEquals("甘N00623", r.primaryPlate)
    }

    @Test
    fun round19_ganP_ganPi_fromUserEval() {
        val r = normalizer.normalize("查询肝屁八七五零九，近期通行记录。")
        assertEquals("甘P87509", r.primaryPlate)
    }

    @Test
    fun round19_qingA_qingLight_fromUserEval() {
        val r = normalizer.normalize("请喝茶车牌号轻AA八八P零车辆信息。")
        assertEquals("青AA88P0", r.primaryPlate)
    }

    @Test
    fun round19_qingD_qingDi_fromUserEval() {
        val r = normalizer.normalize("发现清第八二三三九，涉嫌违章请确。")
        assertEquals("青D82339", r.primaryPlate)
    }

    @Test
    fun round19_qingF_qingF_fromUserEval() {
        val r = normalizer.normalize("通报清FC六六六T为重点关注车辆。")
        assertEquals("青FC666T", r.primaryPlate)
    }

    @Test
    fun round19_qingG_qingG_fromUserEval() {
        val r = normalizer.normalize("追踪目标请G零二幺七六，最后出现在。")
        assertEquals("青G02176", r.primaryPlate)
    }

    @Test
    fun round19_ningE_ningYi_fromUserEval() {
        val r = normalizer.normalize("拦截宁翼幺五九九九，重复请前方不空。")
        assertEquals("宁E15999", r.primaryPlate)
    }

    @Test
    fun round19_ganB_asrLetter_fromUserEval() {
        // ASR 末位 G 非 J
        val r = normalizer.normalize("和对肝病八二六三G是否有保安车辆一致？")
        assertEquals("甘B8263G", r.primaryPlate)
    }

    @Test
    fun round19_qingE_qingYi_fromUserEval() {
        // 青翼→青E 正确；末位 ASR「六七」非 M67 但前缀可提取
        val r = normalizer.normalize("青翼六幺M六七车主请配合检查。")
        assertEquals("青E61M67", r.primaryPlate)
    }

    @Test
    fun round19_qingH_asrLetter_fromUserEval() {
        // ASR 末位 G 非 J
        val r = normalizer.normalize("请HH三九七G请靠边停车接受检查。")
        assertEquals("青HH397G", r.primaryPlate)
    }

    @Test
    fun round19_jiangxiGan_stillWorks_fromUserEval() {
        val r = normalizer.normalize("干H八二C七五车主请配合检查。")
        assertEquals("赣H82C75", r.primaryPlate)
    }

    // round20 新/港澳台/冀R 手测（plate_eval_one_per_plate 333–367）
    @Test
    fun round20_xinD_xianD_fromUserEval() {
        val r = normalizer.normalize("追踪目标先D幺幺A四期，最后出现在。")
        assertEquals("新D11A47", r.primaryPlate)
    }

    @Test
    fun round20_xinE_xinYi_fromUserEval() {
        val r = normalizer.normalize("新翼翼幺二六七，请靠边停车接受检查。")
        assertEquals("新EE1267", r.primaryPlate)
    }

    @Test
    fun round20_xinG_xinZhi_fromUserEval() {
        val r = normalizer.normalize("心智一K六六幺八已纳入拨款名单。")
        assertEquals("新GK6618", r.primaryPlate)
    }

    @Test
    fun round20_xinP_xinPi_fromUserEval() {
        val r = normalizer.normalize("追踪目标新辟六五D九三，最后出现在。")
        assertEquals("新P65D93", r.primaryPlate)
    }

    @Test
    fun round20_xinQ_asrMissingZ_fromUserEval() {
        // ASR 缺字母 Z，仅能到 新Q737K 且位数不足
        val r = normalizer.normalize("新区七三七开，请靠边停车接受检查。")
        assertEquals(null, r.primaryPlate)
    }

    @Test
    fun gaoxinDistrict_notMisheardAsXinjiangPlateQ() {
        val input = "给我看一下成都市高新区桂溪派出所，昨天白天分辖区的接警趋势。"
        val r = normalizer.normalize(input)
        assertTrue("高新区 in ${r.text}", r.text.contains("高新区"))
        assertFalse("高新Q in ${r.text}", r.text.contains("高新Q"))
    }

    @Test
    fun zhengzhouZhengdongDistrict_notMisheardAsXinjiangPlateQ() {
        val input = "帮我统计一下郑州市郑东新区如意湖派出所近七天的接警量。"
        val r = normalizer.normalize(input)
        assertTrue(r.text.contains("郑东新区"))
        assertFalse(r.text.contains("郑东新Q"))
    }

    @Test
    fun round20_gangY_gangWai_fromUserEval() {
        val r = normalizer.normalize("查询港外八V幺幺，近期日通行记录。")
        assertEquals("港Y8V11", r.primaryPlate)
    }

    @Test
    fun round20_aoU_aoU_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号奥U六六五六D车辆信息。")
        // 参考为 6 位澳U656D，ASR 多读一位数字
        assertEquals("澳U6656D", r.primaryPlate)
    }

    @Test
    fun round20_taiwan_tai_asrMissingDigit_fromUserEval() {
        // ASR「四三八八」仅 4 位，凑不出 43888
        val r = normalizer.normalize("拦截台四三八八重复请前方布控。")
        assertEquals(null, r.primaryPlate)
    }

    @Test
    fun round20_jiR22046_gErErLing_fromUserEval() {
        val r = normalizer.normalize("和对G二二零四六是否与抱怨车辆一致？")
        assertEquals("冀R22046", r.primaryPlate)
    }

    @Test
    fun round20_xinM_asrGarbled_fromUserEval() {
        // ASR「一四」非 E4
        val r = normalizer.normalize("新M五六九一四车主请配合检查。")
        assertEquals("新M56914", r.primaryPlate)
    }

    @Test
    fun round20_xinN_asrGarbled_fromUserEval() {
        val r = normalizer.normalize("通报新恩五F六幺四为重点关注车辆。")
        assertEquals("新N5F614", r.primaryPlate)
    }

    @Test
    fun round20_jiR8R228_asrGarbled_fromUserEval() {
        val r = normalizer.normalize("通报G二八二二二二八为重点关注车辆。")
        assertEquals("冀R82228", r.primaryPlate)
    }

    // round21 冀R 续测（plate_eval_one_per_plate 368–400）
    @Test
    fun round21_jiRP086C_jiR_fromUserEval() {
        val r = normalizer.normalize("即RP零八六C已纳入不扣名单。")
        assertEquals("冀RP086C", r.primaryPlate)
    }

    @Test
    fun round21_jiR502P1_jiErErWuLing_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号记二二五零二P幺车辆信息。")
        assertEquals("冀R502P1", r.primaryPlate)
    }

    @Test
    fun round21_jiR6B2Q0_grLiuB_fromUserEval() {
        val r = normalizer.normalize("GR六B二Q零车主请配合检查。")
        assertEquals("冀R6B2Q0", r.primaryPlate)
    }

    @Test
    fun round21_jiR746A2_gErErQi_fromUserEval() {
        val r = normalizer.normalize("通报G二二七四六A二为重点关注车辆。")
        assertEquals("冀R746A2", r.primaryPlate)
    }

    @Test
    fun round21_jiR1853U_grErYao_fromUserEval() {
        val r = normalizer.normalize("追逐目标GR二幺八五三U，最后出现在。")
        assertEquals("冀R1853U", r.primaryPlate)
    }

    @Test
    fun round21_jiR7L326_jiR_beforeOwner_fromUserEval() {
        val r = normalizer.normalize("即R七L三二六车主请配合检查。")
        assertEquals("冀R7L326", r.primaryPlate)
    }

    @Test
    fun round21_jiR95158_grErJiuWu_fromUserEval() {
        val r = normalizer.normalize("查询GR二九五幺五八，近七日通行记录。")
        assertEquals("冀R95158", r.primaryPlate)
    }

    @Test
    fun round21_jiR22585_jiErErWuBa_stillWorks_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号记二二五八五车辆信息。")
        assertEquals("冀R22585", r.primaryPlate)
    }

    @Test
    fun round21_jiR27996_jiErErQi_stillWorks_fromUserEval() {
        val r = normalizer.normalize("帮忙看一下，记二二七九九六车辆近期有没有相关警情？")
        assertEquals("冀R27996", r.primaryPlate)
    }

    // round22 冀RD/冀RF 手测（plate_eval_one_per_plate 401–422）
    @Test
    fun round22_jiRFS9L45_jiRFS_fromUserEval() {
        val r = normalizer.normalize("即RFS九L四五车主请配合检查。")
        assertEquals("冀RFS9L45", r.primaryPlate)
    }

    @Test
    fun round22_jiRFK4T36_shiTi_fromUserEval() {
        val r = normalizer.normalize("通报G RFK实体三六为重点关注车辆。")
        assertEquals("冀RFK4T36", r.primaryPlate)
    }

    @Test
    fun round22_jiRDUG763_jiErDuiUG_fromUserEval() {
        val r = normalizer.normalize("继而对UG七六三请靠边停车接受检查。")
        assertEquals("冀RDUG763", r.primaryPlate)
    }

    @Test
    fun round22_jiRDG5917_jiErDiZhiYi_fromUserEval() {
        val r = normalizer.normalize("和对继而敌制宜五九幺七是否与报案车辆一致？")
        assertEquals("冀RDG5917", r.primaryPlate)
    }

    @Test
    fun round22_jiRDRS044_jiErDRS_fromUserEval() {
        val r = normalizer.normalize("继而DRS零四四已纳入布控名单。")
        assertEquals("冀RDRS044", r.primaryPlate)
    }

    @Test
    fun round22_jiRDY7089_jiErDY_fromUserEval() {
        val r = normalizer.normalize("拦截记而D Y七零八九重复请前方布控。")
        assertEquals("冀RDY7089", r.primaryPlate)
    }

    @Test
    fun round22_jiRDK6741_jiErDiKou_fromUserEval() {
        val r = normalizer.normalize("继而抵扣六七四幺车主请配合检查。")
        assertEquals("冀RDK6741", r.primaryPlate)
    }

    @Test
    fun round22_jiRDU7541_jiErDuiYu_fromUserEval() {
        val r = normalizer.normalize("继而对于七五四幺请靠边停车接受检查。")
        assertEquals("冀RDU7541", r.primaryPlate)
    }

    @Test
    fun round22_jiRFVZ477_grfvz_fromUserEval() {
        val r = normalizer.normalize("和对GRFVZ四七七是否与帮车辆一致？")
        assertEquals("冀RFVZ477", r.primaryPlate)
    }

    @Test
    fun round22_jiRDM235D_jiErDM_fromUserEval() {
        val r = normalizer.normalize("继而DM二三五D已纳入不可名单。")
        assertEquals("冀RDM235D", r.primaryPlate)
    }

    @Test
    fun round22_jiRFV24S1_grfv_fromUserEval() {
        val r = normalizer.normalize("查询GRFV二四S幺近七日通行记录。")
        assertEquals("冀RFV24S1", r.primaryPlate)
    }

    @Test
    fun round22_jiRDL426D_jiErDL_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号，继而DL四二六D车辆信息。")
        assertEquals("冀RDL426D", r.primaryPlate)
    }

    @Test
    fun round22_jiRFY7268_stillWorks_fromUserEval() {
        val r = normalizer.normalize("发现G RFY七二六八涉嫌违章请确认。")
        assertEquals("冀RFY7268", r.primaryPlate)
    }

    // round23 辽B 手测（plate_eval_one_per_plate 423–450）
    @Test
    fun round23_liaoB5E3Q2_wuYi_fromUserEval() {
        val r = normalizer.normalize("辽B五翼三Q二，请靠边停车接受检查。")
        assertEquals("辽B5E3Q2", r.primaryPlate)
    }

    @Test
    fun round23_liaoB08W9R_lingBaW_fromUserEval() {
        val r = normalizer.normalize("查询辽B零八W九R二近七日通行记录。")
        assertEquals("辽B08W9R", r.primaryPlate)
    }

    @Test
    fun round23_liaoB572B4_biSi_fromUserEval() {
        val r = normalizer.normalize("通报辽B五七二壁寺为重点关注车辆。")
        assertEquals("辽B572B4", r.primaryPlate)
    }

    @Test
    fun round23_liaoB91107_lingQi_fromUserEval() {
        val r = normalizer.normalize("辽B九幺幺零期请靠边停车接受检查。")
        assertEquals("辽B91107", r.primaryPlate)
    }

    @Test
    fun round23_liaoB098D5_stillWorks_fromUserEval() {
        val r = normalizer.normalize("发现辽B零九八第五涉嫌违章请确认。")
        assertEquals("辽B098D5", r.primaryPlate)
    }

    // round24 辽B/BF/BD 手测（plate_eval_one_per_plate 451–492）
    @Test
    fun round24_liaoBDZ583P_spaceZ_fromUserEval() {
        val r = normalizer.normalize("辽B Z五八三P车主请检查。")
        assertEquals("辽BDZ583P", r.primaryPlate)
    }

    @Test
    fun round24_liaoBDY530G_wai_fromUserEval() {
        val r = normalizer.normalize("追踪目标，辽BD外五三零G最后出现在。")
        assertEquals("辽BDY530G", r.primaryPlate)
    }

    @Test
    fun round24_liaoBDP6S88_diP_fromUserEval() {
        val r = normalizer.normalize("辽B地P六S八八，请靠边停车接受检查。")
        assertEquals("辽BDP6S88", r.primaryPlate)
    }

    @Test
    fun round24_liaoBDG6787_diZhiYi_fromUserEval() {
        val r = normalizer.normalize("辽B地制宜六七八七，车主请配合检查。")
        assertEquals("辽BDG6787", r.primaryPlate)
    }

    @Test
    fun round24_liaoBFWJ544_spaceFwj_fromUserEval() {
        val r = normalizer.normalize("辽B FWJ五四四，请靠边停车接受检查。")
        assertEquals("辽BFWJ544", r.primaryPlate)
    }

    @Test
    fun round24_liaoBDD8K07_diDi_fromUserEval() {
        val r = normalizer.normalize("辽B弟弟八K零七已纳入布控名单。")
        assertEquals("辽BDD8K07", r.primaryPlate)
    }

    @Test
    fun round24_liaoBFD55P6_wuWuP_fromUserEval() {
        val r = normalizer.normalize("请核查车牌号辽BFD五五P六车辆信息。")
        assertEquals("辽BFD55P6", r.primaryPlate)
    }

    @Test
    fun round24_liaoBDN3609_orphanBdn_fromUserEval() {
        val r = normalizer.normalize("追逐目标BDN三六零九，最后出现在。")
        assertEquals("辽BDN3609", r.primaryPlate)
    }

    @Test
    fun round24_liaoBFR4924_stillWorks_fromUserEval() {
        val r = normalizer.normalize("发现辽BFR四九二四摄像违章请确认。")
        assertEquals("辽BFR4924", r.primaryPlate)
    }

    // round25 P1 gpu3 dialogue：F 谐音前缀 + D 中文数字/候选截断
    private fun p1Normalizer(): PlateNormalizer {
        val path = java.nio.file.Paths.get("src/main/assets/plate/plate_homophones.csv")
        val dict = PlateHomophoneDict.loadFromReader(
            BufferedReader(java.io.FileReader(path.toFile(), Charsets.UTF_8)),
        )
        return PlateNormalizer.create(dict)
    }

    @Test
    fun round25_p0_F_jiEr91648_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("我们已经记录继尔九幺六四八，请您先不要和车主发生。")
        assertEquals("冀R91648", r.primaryPlate)
    }

    @Test
    fun round25_p0_F_jieEr26732_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号接二二六七三二的司机开车时一直压线，我担心路上不安全。")
        assertEquals("冀R26732", r.primaryPlate)
    }

    @Test
    fun round25_p0_F_liuBi20342_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号六笔二零三四二一登记附近巡逻人员会按位置过去查。")
        assertEquals("辽B20342", r.primaryPlate)
    }

    @Test
    fun round25_p0_F_jiEr73504_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("关于继而七三五零四的情况，我们会核查，您不要上前盘问。")
        assertEquals("冀R73504", r.primaryPlate)
    }

    @Test
    fun round25_p0_F_jiR17090_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("我看到车牌号记R一七零九零的车撞到护栏后，没有停往北边开走。")
        assertEquals("冀R17090", r.primaryPlate)
    }

    @Test
    fun round25_p0_D_jiR14278_chineseDigits_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号即R一四二七八相关线索已保存，后续可能需要您补充照片。")
        assertEquals("冀R14278", r.primaryPlate)
        assertTrue(r.text.contains("冀R14278"))
    }

    @Test
    fun round25_p0_D_liaoB82463_extraDigit_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("我们已经记录车牌号辽B八二四六三七零，保持现场安全，民警会尽快核实。")
        assertEquals("辽B82463", r.primaryPlate)
    }

    @Test
    fun round25_p0_D_liaoB88260_chineseDigits_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌后，辽B八八二六零相关线索已保存，后续可能需要您补充照片。")
        assertEquals("辽B88260", r.primaryPlate)
    }

    @Test
    fun round25_p0_D_jiR46222_doubleZero_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号GR四六二二零零旅附近巡逻人员会按位置过去查看。")
        assertEquals("冀R46222", r.primaryPlate)
    }

    @Test
    fun round25_p0_jiR37539_jiR_notJiLin_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号及R三七五三九的车窗没有关，外面正在下雨，我想帮忙联系车主。")
        assertEquals("冀R37539", r.primaryPlate)
    }

    // round26 P1 gpu3 dialogue：H 纯口语 + Z 辽B 变体
    @Test
    fun round26_p1_H_yiEr67240_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("以二六七二四零这辆车倒车的时候，碰到我电动车了。")
        assertEquals("冀R67240", r.primaryPlate)
    }

    @Test
    fun round26_p1_H_liaoBi41482_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("刚才车牌号撩壁，四幺四八二的车在路口突然变道，差点把我撞倒。")
        assertEquals("辽B41482", r.primaryPlate)
    }

    @Test
    fun round26_p1_H_haoLiao04877_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌好料别零四八七七。如果造成堵塞，请您告诉我堵塞持续了多久？")
        assertEquals("辽B04877", r.primaryPlate)
    }

    @Test
    fun round26_p1_H_infer40957_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("我这边要报警，车牌号七二四零九五七的车，刚才把我车左侧刮了一下，现在还停在路边。")
        assertEquals("冀R40957", r.primaryPlate)
    }

    @Test
    fun round26_p1_H_infer51640_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号九二五幺六四零，如果存在危险停放，我们会通知相关人员尽快处置。")
        assertEquals("冀R51640", r.primaryPlate)
    }

    @Test
    fun round26_p1_H_jiEr55622_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号吉二五五六二二，如果存在危险停放，我们会通知相关人员尽快处。")
        assertEquals("冀R55622", r.primaryPlate)
    }

    @Test
    fun round26_p1_H_jiBa09185_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号即八零九幺八五的车主联系情况，我们会跟进，请您耐心等候。")
        assertEquals("冀R09185", r.primaryPlate)
    }

    @Test
    fun round26_p1_H_orphan34896_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("一二三四八九六刚才经过水坑，把我和孩子溅了一身。")
        assertEquals("冀R34896", r.primaryPlate)
    }

    @Test
    fun round26_p1_Z_liaoB02000_fromDialogueEval() {
        val n = p1Normalizer()
        val text = "车牌号辽B零二零零。刚才从水坑旁边快速开过，把行人溅了一身水。"
        val r = n.normalize(text)
        assertEquals("辽B02000", r.primaryPlate)
    }

    @Test
    fun round26_p1_Z_liaoB98677_series_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号辽B九八六七系列车挡住了店门口，泄火通道，司机一直联系不上。")
        assertEquals("辽B98677", r.primaryPlate)
    }

    @Test
    fun round26_p1_Z_liaoB16163_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号辽B幺六幺六三相关线索已保存，后续可能需要您补充照。")
        assertEquals("辽B16163", r.primaryPlate)
    }

    @Test
    fun round26_p1_Z_liaoB66345_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号辽B六六三四五五的信息已登记，请您先不要和对方发生争执。")
        assertEquals("辽B66345", r.primaryPlate)
    }

    @Test
    fun round26_p1_Z_liaoB85760_baiLing_fromDialogueEval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号辽B八五七六百零的车挡住了店门口，卸货通道，司机一直联系不上。")
        assertEquals("辽B85760", r.primaryPlate)
    }

    // round27 gpu13 口音对话集
    @Test
    fun round27_accent_qiR62620_fromGpu13Eval() {
        val n = p1Normalizer()
        val r = n.normalize("我这边要报警，车牌号气R六二六二零的车，刚才把我车左侧刮了一下，现在还停。")
        assertEquals("冀R62620", r.primaryPlate)
    }

    @Test
    fun round27_accent_jieEr67715_fromGpu13Eval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号接，而六七七幺五的车窗没有关，外面正在下雨，我想帮忙联系车主。")
        assertEquals("冀R67715", r.primaryPlate)
    }

    @Test
    fun round27_accent_jiEr73504_fromGpu13Eval() {
        val n = p1Normalizer()
        val r = n.normalize("我怀疑继儿七三五零四，这辆车一直在我们小区门口转行为有点异常。")
        assertEquals("冀R73504", r.primaryPlate)
    }

    @Test
    fun round27_accent_uAsOne45013_fromGpu13Eval() {
        val n = p1Normalizer()
        val r = n.normalize("我们已经记录车牌号辽B四五零U三，请您保持现场安全，民警会尽快核。")
        assertEquals("辽B45013", r.primaryPlate)
    }

    @Test
    fun round27_accent_grU14079_fromGpu13Eval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号GR U四零七九的车门没关好，车里还有包，我怕车主东西。")
        assertEquals("冀R14079", r.primaryPlate)
    }

    @Test
    fun round27_accent_yaoBi56028_fromGpu13Eval() {
        val n = p1Normalizer()
        val r = n.normalize("姚碧五六零二八后备箱位关闭，我们会尝试联系车主。")
        assertEquals("辽B56028", r.primaryPlate)
    }

    @Test
    fun round27_accent_yeSuffix95191_fromGpu13Eval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号辽B九五幺九耶的情况，我们会转给附近警力，请您留意车辆当前位置。")
        assertEquals("辽B95191", r.primaryPlate)
    }

    @Test
    fun round27_accent_infer55622_fromGpu13Eval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号七二五六二二，如果存在危险停放，我们会通知相关人员尽快处置。")
        assertEquals("冀R55622", r.primaryPlate)
    }

    // round28 P0：全量 1076 真机未命中可修 case
    @Test
    fun round28_p0_jiErEr22780_fromFull1076Eval() {
        val n = p1Normalizer()
        val r = n.normalize("请您拍下车牌号记二二七八零车辆所在位置，方便后续核查。")
        assertEquals("冀R22780", r.primaryPlate)
    }

    @Test
    fun round28_p0_jiEr26445_fromFull1076Eval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号即二六四四五的情况，我们会转给附近警力，请您留意车辆当前位置。")
        assertEquals("冀R26445", r.primaryPlate)
    }

    @Test
    fun round28_p0_orphan34896_fromFull1076Eval() {
        val n = p1Normalizer()
        val r = n.normalize("一二三四八九六钢材经过水坑，把我和孩子接了一身。")
        assertEquals("冀R34896", r.primaryPlate)
    }

    @Test
    fun round28_p0_jiErLing05477_fromFull1076Eval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号记二零五四七七一路入，请，您说明是否有人受伤或财务？")
        assertEquals("冀R05477", r.primaryPlate)
    }

    @Test
    fun round28_p0_jiEr00300_ban_fromFull1076Eval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号继二零零三版钢材在高架入口急刹后。车差点追尾。")
        assertEquals("冀R00300", r.primaryPlate)
    }

    @Test
    fun round28_p0_gEr00300_mei_fromFull1076Eval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号G二零零三零枚，刚才在高架入口急刹候车差点追尾。")
        assertEquals("冀R00300", r.primaryPlate)
    }

    @Test
    fun round28_p0_jiEr00300_lang_fromFull1076Eval() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号即二零零三郎零相关线索已保存，后续可能需要您补充照片。")
        assertEquals("冀R00300", r.primaryPlate)
    }

    // round29 新声学 round01：G/72X 分段阿拉伯数字
    @Test
    fun round29_newAcoustic_gSpaced215974_fromRound01() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号G 215 974如果已经离开，请您告诉我他最后驶离的方向。")
        assertEquals("冀R15974", r.primaryPlate)
    }

    @Test
    fun redTeam_g215974Unspaced_fromRound01() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号G215974如果已经离开请您告诉我他最后驶离的方向。")
        assertEquals("冀R15974", r.primaryPlate)
    }

    @Test
    fun redTeam_gr2024ProductCode_notPlate() {
        val n = p1Normalizer()
        val r = n.normalize("产品型号为 GR2024 标准版已上市。")
        assertEquals("产品型号为 GR2024 标准版已上市。", r.text)
    }

    @Test
    fun round29_newAcoustic_72x12760_fromRound01() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号721 2760在斑马线前没有礼让行人老人差点被。")
        assertEquals("冀R12760", r.primaryPlate)
    }

    @Test
    fun round29_newAcoustic_ji231054_fromRound01() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号记231 054的情况已记录，请您先把车辆停到安全区域。")
        assertEquals("冀R31054", r.primaryPlate)
    }

    @Test
    fun round29_newAcoustic_liaoB02000_fromRound01() {
        val n = p1Normalizer()
        val r = n.normalize("车牌号辽B 020里刚才从水坑旁边快速开过，把行人溅了一身。")
        assertEquals("辽B02000", r.primaryPlate)
    }

}
