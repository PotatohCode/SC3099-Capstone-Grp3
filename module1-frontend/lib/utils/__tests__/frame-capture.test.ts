import { BURST_JPEG, createFrameGrabber, PHOTO_JPEG } from '@/lib/utils/frame-capture'

function setup(dataUrl = 'data:image/jpeg;base64,QUJD') {
  const ctx = { drawImage: jest.fn(), scale: jest.fn(), setTransform: jest.fn(), translate: jest.fn(), transform: jest.fn() }
  const canvases: HTMLCanvasElement[] = []
  const realCreate = document.createElement.bind(document)
  jest.spyOn(document, 'createElement').mockImplementation((tag: string) => {
    const el = realCreate(tag)
    if (tag === 'canvas') {
      Object.assign(el, { getContext: jest.fn(() => ctx), toDataURL: jest.fn(() => dataUrl) })
      canvases.push(el as HTMLCanvasElement)
    }
    return el
  })
  return { ctx, canvases }
}

function video(width: number, height: number): HTMLVideoElement {
  return { videoWidth: width, videoHeight: height } as HTMLVideoElement
}

describe('createFrameGrabber', () => {
  afterEach(() => jest.restoreAllMocks())

  it('returns raw base64 without the data: prefix', () => {
    setup()
    expect(createFrameGrabber(video(640, 480), BURST_JPEG)()).toBe('QUJD')
  })

  it('scales to 640 px wide keeping the aspect ratio', () => {
    const { canvases, ctx } = setup()
    const v = video(1280, 720)
    createFrameGrabber(v, BURST_JPEG)()
    expect([canvases[0].width, canvases[0].height]).toEqual([640, 360])
    expect(ctx.drawImage).toHaveBeenCalledWith(v, 0, 0, 640, 360)
  })

  it('keeps 640x480 as is', () => {
    const { canvases } = setup()
    createFrameGrabber(video(640, 480), BURST_JPEG)()
    expect([canvases[0].width, canvases[0].height]).toEqual([640, 480])
  })

  it('never flips or transforms the frame', () => {
    const { ctx } = setup()
    createFrameGrabber(video(640, 480), BURST_JPEG)()
    expect(ctx.scale).not.toHaveBeenCalled()
    expect(ctx.setTransform).not.toHaveBeenCalled()
    expect(ctx.translate).not.toHaveBeenCalled()
    expect(ctx.transform).not.toHaveBeenCalled()
  })

  it('uses JPEG quality 0.7 for bursts and 0.8 for photos', () => {
    const { canvases } = setup()
    createFrameGrabber(video(640, 480), BURST_JPEG)()
    createFrameGrabber(video(640, 480), PHOTO_JPEG)()
    expect(canvases[0].toDataURL).toHaveBeenCalledWith('image/jpeg', 0.7)
    expect(canvases[1].toDataURL).toHaveBeenCalledWith('image/jpeg', 0.8)
  })

  it('returns null while the video has no frame yet, or on an empty encode', () => {
    setup()
    expect(createFrameGrabber(video(0, 0), BURST_JPEG)()).toBeNull()
    jest.restoreAllMocks()
    setup('data:,')
    expect(createFrameGrabber(video(640, 480), BURST_JPEG)()).toBeNull()
  })

  it('reuses one canvas across grabs', () => {
    const { canvases } = setup()
    const grab = createFrameGrabber(video(640, 480), BURST_JPEG)
    grab()
    grab()
    grab()
    expect(canvases).toHaveLength(1)
  })
})
