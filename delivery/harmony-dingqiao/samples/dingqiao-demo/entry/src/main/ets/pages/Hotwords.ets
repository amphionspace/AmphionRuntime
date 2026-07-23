import { common } from '@kit.AbilityKit';
import { promptAction, router } from '@kit.ArkUI';
import { DemoPrefs } from '../util/DemoPrefs';

const MAX_LEN = 60;
const BRAND_ACCENT = '#2E6BE6';

/**
 * Custom hotword management. Words are written to DemoPrefs and passed to the SDK as sysGeneralLexicon
 * by the main page (which rebuilds the engine when it detects a change on return).
 */
@Entry
@Component
struct Hotwords {
  @State items: string[] = [];
  @State inputText: string = '';

  aboutToAppear(): void {
    this.items = DemoPrefs.getUserHotwords(getContext(this) as common.UIAbilityContext);
  }

  private save(): void {
    DemoPrefs.setUserHotwords(getContext(this) as common.UIAbilityContext, this.items);
  }

  private addHotword(): void {
    const text = this.inputText.trim();
    if (text.length === 0 || text.length > MAX_LEN) {
      this.toast('热词不能为空且不超过 60 字');
      return;
    }
    if (this.items.some((w: string): boolean => w === text)) {
      this.toast('该热词已存在');
      return;
    }
    const next = this.items.slice();
    next.push(text);
    this.items = next;
    this.inputText = '';
    this.save();
  }

  private deleteAt(index: number): void {
    if (index < 0 || index >= this.items.length) return;
    const next = this.items.slice();
    next.splice(index, 1);
    this.items = next;
    this.save();
  }

  private toast(message: string): void {
    promptAction.showToast({ message: message, duration: 2000 });
  }

  build() {
    Column({ space: 12 }) {
      Row({ space: 8 }) {
        Text('返回').fontSize(16).fontColor(BRAND_ACCENT).onClick((): void => { router.back(); })
        Text('自定义热词').fontSize(20).fontWeight(FontWeight.Bold).layoutWeight(1)
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)

      Text('此处添加的词会作为 sysGeneralLexicon 传入 SDK。')
        .fontSize(12)
        .fontColor(Color.Gray)
        .width('100%')

      Row({ space: 8 }) {
        TextInput({ text: this.inputText, placeholder: '例如：盘查、张三' })
          .layoutWeight(1)
          .onChange((value: string): void => { this.inputText = value; })
          .onSubmit((): void => this.addHotword())
        Button('添加').onClick((): void => this.addHotword())
      }
      .width('100%')

      Text(`已添加 ${this.items.length} 条自定义热词`).fontSize(13).fontColor(Color.Gray).width('100%')

      Scroll() {
        Column({ space: 8 }) {
          if (this.items.length === 0) {
            Text('还没有自定义热词').fontSize(14).fontColor(Color.Gray).width('100%')
          }
          ForEach(this.items, (item: string, index: number) => {
            Row() {
              Text(item).fontSize(16).layoutWeight(1)
              Text('删除').fontSize(14).fontColor('#E5533C').onClick((): void => this.deleteAt(index))
            }
            .width('100%')
            .padding({ top: 8, bottom: 8 })
            .alignItems(VerticalAlign.Center)
          }, (item: string, index: number) => `${index}-${item}`)
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
      }
      .layoutWeight(1)
      .width('100%')
      .backgroundColor('#f5f5f5')
      .borderRadius(8)
      .padding(12)
      .align(Alignment.TopStart)
    }
    .padding(20)
    .width('100%')
    .height('100%')
    .alignItems(HorizontalAlign.Start)
  }
}
