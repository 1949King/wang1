"""
AI特效制作插件 - 快速验证脚本
用于测试插件是否能够正确加载和运行
"""

import sys
import os

import logging
logger = logging.getLogger("AI短剧编辑器.plugins.ai_effects_plugin.test_plugin")

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

def test_plugin_loading():
    """测试插件加载"""
    logger.info('=' * 60)
    logger.info('🔍 测试AI特效制作插件')
    logger.info('=' * 60)
    
    try:
        # 1. 导入插件
        logger.info('\n[1/5] 正在导入插件模块...')
        from app.plugins.ai_effects_plugin import Plugin, AIEffectsWidget, PLUGIN_INFO
        
        logger.info(f'   ✅ 插件导入成功')
        logger.info(f'   📋 插件信息:')
        logger.info(f"      - 名称: {PLUGIN_INFO['name']}")
        logger.info(f"      - 版本: {PLUGIN_INFO['version']}")
        logger.info(f"      - 作者: {PLUGIN_INFO['author']}")
        logger.info(f"      - 分类: {PLUGIN_INFO['category']}")
        
        # 2. 创建插件实例
        logger.info('\n[2/5] 创建插件实例...')
        plugin = Plugin()
        logger.info(f'   ✅ 插件实例创建成功 (ID: {plugin.plugin_info.id})')
        
        # 3. 验证插件
        logger.info('\n[3/5] 验证插件配置...')
        is_valid = plugin.validate()
        if is_valid:
            logger.info(f'   ✅ 插件验证通过')
        else:
            logger.info(f'   ⚠️ 插件验证未完全通过（部分可选依赖缺失）')
        
        # 4. 初始化插件
        logger.info('\n[4/5] 初始化插件...')
        context = {
            'models_path': './models/ai_effects',
            'gpu_enabled': False,  # 演示模式使用CPU
            'cache_dir': './cache/test'
        }
        init_success = plugin.initialize(context)
        if init_success:
            logger.info(f'   ✅ 插件初始化成功')
        else:
            logger.error(f'   ❌ 插件初始化失败')
            return False
        
        # 5. 获取UI配置和支持的特效列表
        logger.info('\n[5/5] 获取插件功能信息...')
        ui_config = plugin.get_ui_config()
        logger.info(f'   ✅ UI配置获取成功')
        logger.info(f"   📐 UI名称: {ui_config['name']}")
        logger.info(f"   🎨 图标: {ui_config['icon']}")
        logger.info(f"   🔧 参数组数量: {len(ui_config['params'])}")
        
        supported_effects = plugin.get_supported_effects()
        logger.info(f'\n   🎬 支持的特效 ({len(supported_effects)}种):')
        for effect in supported_effects:
            status = "✅ 已就绪" if effect['loaded'] else "⏳ 待加载"
            logger.info(f"      - {effect['name']:20s} [{status}]")
        
        # 6. 获取参数定义示例
        logger.info('\n📖 参数定义预览（风格迁移）:')
        plugin._current_effect = type('AIEffectType', (), {'value': 'style_transfer'})()
        params_def = plugin.get_effect_params()
        if params_def:
            for param_name, param_info in list(params_def.items())[:4]:
                logger.info(f"   • {param_name}: {param_info.get('type', 'unknown')}")
                logger.info(f"     默认值: {param_info.get('default', 'N/A')}")
                if 'options' in param_info:
                    options_str = ', '.join(str(o) for o in param_info['options'])
                    logger.info(f'     可选项: {options_str[:60]}...')
        
        logger.info('\n' + '=' * 60)
        logger.info('🎉 所有基础测试通过！插件已准备就绪。')
        logger.info('=' * 60)
        
        # 清理
        plugin.shutdown()
        
        return True
        
    except ImportError as e:
        logger.error(f'\n❌ 导入失败: {e}')
        logger.info('\n可能的原因:')
        logger.info('  1. Python路径配置不正确')
        logger.info('  2. 缺少必要的依赖库 (numpy, opencv-python等)')
        return False
        
    except Exception as e:
        logger.error(f'\n❌ 测试过程中出现错误: {e}')
        import traceback
        traceback.print_exc()
        return False


def test_image_processing():
    """测试图像处理功能（需要OpenCV和numpy）"""
    logger.info('\n\n' + '=' * 60)
    logger.info('🖼️ 测试图像处理能力')
    logger.info('=' * 60)
    
    try:
        import numpy as np
        import cv2
        
        from app.plugins.ai_effects_plugin.main import Plugin, AIEffectType
        
        # 创建测试图像（200x150 彩色渐变）
        logger.info('\n📸 创建测试图像 (200x150)...')
        test_image = np.zeros((150, 200, 3), dtype=np.uint8)
        for y in range(150):
            for x in range(200):
                test_image[y, x] = [
                    int(x / 200 * 255),   # B
                    int(y / 150 * 255),   # G
                    128                    # R
                ]
        
        logger.info(f'   ✅ 测试图像已创建 (shape: {test_image.shape})')
        
        # 初始化插件
        plugin = Plugin()
        plugin.initialize({'gpu_enabled': False})
        
        # 测试1：风格迁移
        logger.info('\n[测试1] 应用赛博朋克风格迁移...')
        result_style = plugin.apply_effect(test_image.copy(), {
            'effect_type': 'style_transfer',
            'style_name': 'cyberpunk',
            'style_strength': 0.8,
            'preserve_color': True
        })
        logger.info(f'   ✅ 风格迁移完成 (输出: {result_style.shape})')
        
        # 测试2：超分辨率
        logger.info('\n[测试2] 应用2倍超分辨率...')
        result_sr = plugin.apply_effect(test_image.copy(), {
            'effect_type': 'super_resolution',
            'scale_factor': '2',
            'model_quality': 'fast',
            'denoise_strength': 0.2
        })
        logger.info(f'   ✅ 超分辨率完成 ({test_image.shape} → {result_sr.shape})')
        assert result_sr.shape[0] == test_image.shape[0] * 2, "放大尺寸不匹配"
        assert result_sr.shape[1] == test_image.shape[1] * 2, "放大尺寸不匹配"
        
        # 测试3：背景替换（使用模糊）
        logger.info('\n[测试3] 应用背景替换（模糊模式）...')
        result_bg = plugin.apply_effect(test_image.copy(), {
            'effect_type': 'background_replace',
            'background_type': 'blur',
            'blur_strength': 15,
            'edge_smoothness': 5
        })
        logger.info(f'   ✅ 背景替换完成 (输出: {result_bg.shape})')
        
        # 测试4：智能美颜
        logger.info('\n[测试4] 应用智能美颜效果...')
        result_beauty = plugin.apply_effect(test_image.copy(), {
            'effect_type': 'beauty_filter',
            'smoothing': 0.5,
            'whitening': 0.3,
            'face_slimming': 0.2,
            'eye_enlargement': 0.15,
            'natural_look': True
        })
        logger.info(f'   ✅ 美颜效果完成 (输出: {result_beauty.shape})')
        
        # 测试5：物体移除
        logger.info('\n[测试5] 应用物体移除...')
        # 在图像中心画一个矩形作为待移除物体
        test_with_obj = test_image.copy()
        cv2.rectangle(test_with_obj, (70, 40), (130, 110), (0, 0, 255), -1)
        
        result_removal = plugin.apply_effect(test_with_obj, {
            'effect_type': 'object_removal',
            'removal_mode': 'manual_select',
            'fill_method': 'ai_inpainting',
            'edge_feathering': 10,
            'selected_rect': (70, 40, 60, 70)  # x, y, w, h
        })
        logger.info(f'   ✅ 物体移除完成 (输出: {result_removal.shape})')
        
        # 清理
        plugin.shutdown()
        
        logger.info('\n' + '=' * 60)
        logger.info('🎉 所有图像处理测试通过！')
        logger.info('=' * 60)
        
        return True
        
    except AssertionError as e:
        logger.error(f'\n❌ 断言失败: {e}')
        return False
    except Exception as e:
        logger.error(f'\n❌ 图像处理测试失败: {e}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    print("\n" + "🎨" * 30)
    print("       AI特效制作插件 - 自动化测试套件")
    print("🎨" * 30 + "\n")
    
    # 运行测试
    test1_pass = test_plugin_loading()
    
    if test1_pass:
        test2_pass = test_image_processing()
        
        if test1_pass and test2_pass:
            print("\n\n✅✅✅  全部测试通过！插件可以正常工作。  ✅✅✅\n")
            sys.exit(0)
        else:
            print("\n\n⚠️  部分测试未通过，请检查错误信息。  ⚠️\n")
            sys.exit(1)
    else:
        print("\n\n❌ 基础加载测试失败，跳过后续测试。  ❌\n")
        sys.exit(2)
